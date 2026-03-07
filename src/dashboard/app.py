"""Web dashboard for PolySuite."""

import hashlib
import hmac
import logging
import os
import time
from urllib.parse import parse_qsl

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from src.wallet.storage import WalletStorage

logger = logging.getLogger(__name__)

# auth_date max age in seconds (24 hours) - CRIT-001 replay protection
INIT_DATA_MAX_AGE_SECONDS = 86400


def _validate_telegram_init_data(init_data: str, bot_token: str) -> bool:
    """Validate Telegram WebApp initData per Telegram docs. Returns True if valid.

    Validates HMAC and auth_date to prevent replay attacks (CRIT-001).
    """
    if not init_data or not bot_token:
        return False
    try:
        parsed = dict(parse_qsl(init_data))
        hash_val = parsed.pop("hash", None)
        if not hash_val:
            return False
        # HIGH-005: Require auth_date for replay protection; reject if missing
        auth_date_str = parsed.get("auth_date")
        if not auth_date_str:
            return False
        # CRIT-001: Reject initData older than INIT_DATA_MAX_AGE_SECONDS
        try:
            auth_ts = int(auth_date_str)
            if time.time() - auth_ts > INIT_DATA_MAX_AGE_SECONDS:
                return False
        except (ValueError, TypeError):
            return False
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(
            bot_token.encode(), b"WebAppData", hashlib.sha256
        ).digest()
        computed = hmac.new(
            secret_key, data_check.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, hash_val)
    except Exception:
        return False


class Dashboard:
    """Web dashboard for PolySuite."""

    def __init__(self, storage: WalletStorage, socketio: SocketIO):
        """Initialize the dashboard."""
        self.app = Flask(__name__)
        # MED-004: Set Flask secret from env
        self.app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())
        # HIGH-002: Require explicit CORS origins; no * default in production
        cors_origins = os.getenv("DASHBOARD_CORS_ORIGINS", "").strip()
        CORS(self.app, origins=cors_origins.split(",") if cors_origins else ["http://127.0.0.1:5000"])
        self.socketio = socketio
        self.storage = storage
        self._api_key = os.getenv("DASHBOARD_API_KEY", "").strip()
        self._require_auth = os.getenv("DASHBOARD_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
        # MED-002: Fail startup if auth required but no key set
        if self._require_auth and not self._api_key:
            raise RuntimeError(
                "DASHBOARD_REQUIRE_AUTH is set but DASHBOARD_API_KEY is missing. "
                "Set DASHBOARD_API_KEY in .env when exposing dashboard beyond localhost."
            )

        # Attach the app to the socketio instance
        self.socketio.init_app(self.app)

        # MED-003: Simple in-memory rate limit for /api/verify (per IP)
        self._verify_attempts: dict = {}

        def _check_auth():
            """HIGH-001: API key via header only (no query string)."""
            if not self._api_key and not self._require_auth:
                return True
            provided = request.headers.get("X-API-Key")
            return provided == self._api_key if self._api_key else True

        @self.app.before_request
        def _auth_middleware():
            if request.path in ("/", "/connect-polymarket", "/connect-kalshi") or request.path.startswith("/static"):
                if not _check_auth():
                    return "Unauthorized", 401

        @self.app.route("/")
        def index():
            if not _check_auth():
                return "Unauthorized", 401
            wallets = self.storage.list_wallets()
            return render_template("index.html", wallets=wallets)

        @self.app.route("/connect-polymarket")
        def connect_polymarket():
            if not _check_auth():
                return "Unauthorized", 401
            return render_template("connect_polymarket.html")

        @self.app.route("/connect-kalshi")
        def connect_kalshi():
            if not _check_auth():
                return "Unauthorized", 401
            return render_template("connect_kalshi.html")

        @self.app.route("/api/polymarket/store-credentials", methods=["POST"])
        def store_polymarket_creds():
            if not _check_auth():
                return jsonify({"ok": False, "error": "Unauthorized"}), 401
            try:
                data = request.get_json() or {}
                user_id = (data.get("user_id") or "").strip()
                api_key = (data.get("api_key") or "").strip()
                api_secret = (data.get("api_secret") or "").strip()
                api_passphrase = (data.get("api_passphrase") or "").strip()
                if not user_id or not api_key or not api_secret or not api_passphrase:
                    return jsonify({"ok": False, "error": "Missing user_id, api_key, api_secret, or api_passphrase"}), 400
                from src.auth.credential_store import store_credentials
                store_credentials(user_id, "polymarket", {"api_key": api_key, "api_secret": api_secret, "api_passphrase": api_passphrase})
                return jsonify({"ok": True})
            except RuntimeError:
                return jsonify({"ok": False, "error": "Credential storage not configured"}), 500
            except Exception as e:
                logger.exception("store_polymarket_creds: %s", e)
                return jsonify({"ok": False, "error": "Failed to store credentials"}), 500

        @self.app.route("/api/kalshi/store-credentials", methods=["POST"])
        def store_kalshi_creds():
            if not _check_auth():
                return jsonify({"ok": False, "error": "Unauthorized"}), 401
            try:
                data = request.get_json() or {}
                user_id = (data.get("user_id") or "").strip()
                api_key_id = (data.get("api_key_id") or "").strip()
                private_key_pem = (data.get("private_key_pem") or "").strip()
                if not user_id or not api_key_id or not private_key_pem:
                    return jsonify({"ok": False, "error": "Missing user_id, api_key_id, or private_key_pem"}), 400
                from src.auth.credential_store import store_credentials
                store_credentials(user_id, "kalshi", {"api_key_id": api_key_id, "private_key_pem": private_key_pem})
                return jsonify({"ok": True})
            except RuntimeError:
                return jsonify({"ok": False, "error": "Credential storage not configured"}), 500
            except Exception as e:
                logger.exception("store_kalshi_creds: %s", e)
                return jsonify({"ok": False, "error": "Failed to store credentials"}), 500

        @self.app.route("/api/verify", methods=["POST"])
        def verify_init_data():
            """Validate Telegram initData. For use when Mini App needs server-side auth."""
            # MED-003: Rate limit by IP
            client_ip = request.remote_addr or "unknown"
            now = time.time()
            attempts = self._verify_attempts
            if client_ip in attempts:
                last, count = attempts[client_ip]
                if now - last < 60 and count >= 30:  # 30 req/min per IP
                    return jsonify({"valid": False, "error": "rate_limit"}), 429
                if now - last > 60:
                    attempts[client_ip] = (now, 1)
                else:
                    attempts[client_ip] = (last, count + 1)
            else:
                attempts[client_ip] = (now, 1)
            # Prune old entries
            for ip in list(attempts):
                if now - attempts[ip][0] > 120:
                    del attempts[ip]
            init_data = (request.json or {}).get("initData", "")
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            if _validate_telegram_init_data(init_data, bot_token):
                return jsonify({"valid": True})
            return jsonify({"valid": False}), 401

        @self.socketio.on("connect")
        def handle_connect():
            """HIGH-003: Require initData or API key for Socket.IO. LOW-006: Never log initData value."""
            init_data = request.args.get("initData", "")
            api_key = request.headers.get("X-API-Key", "")
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            if self._api_key and api_key == self._api_key:
                logger.info("Client connected (API key)")
                return
            if init_data and bot_token and _validate_telegram_init_data(init_data, bot_token):
                logger.info("Client connected (initData)")
                return
            if not self._api_key and not self._require_auth:
                logger.info("Client connected (no auth)")
                return
            from flask_socketio import disconnect
            disconnect()

    def run(self):
        """Run the dashboard. Disable debug in production (CRIT-001)."""
        debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
        self.socketio.run(self.app, debug=debug)
