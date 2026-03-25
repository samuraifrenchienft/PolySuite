"""Web dashboard for PolySuite."""

import atexit
import json
import logging
import os
import threading
import random
import string
import time
from datetime import datetime

logger = logging.getLogger(__name__)


def _generate_random_nickname():
    """Generate a readable random nickname for wallets with none (e.g. Trader_K7m2)."""
    prefixes = ("Trader", "Alpha", "Swift", "Bold", "Quick", "Smart", "Apex", "Nova")
    prefix = random.choice(prefixes)
    suffix = random.choice(string.ascii_uppercase) + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=3)
    )
    return f"{prefix}_{suffix}"
from flask import Flask, render_template, request, abort, jsonify, send_from_directory, make_response
from src.wallet.storage import WalletStorage
from src.wallet.classifier import WalletClassifier
from src.wallet import Wallet
from src.auth.credential_store import store_credentials, get_credentials
from src.config import Config, max_tracked_wallets
from src.market.api import APIClientFactory


# Get the correct template path
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


class Dashboard:
    """Web dashboard for PolySuite."""

    def __init__(self, storage: WalletStorage, config=None, api_factory=None):
        """Initialize the dashboard.

        Args:
            storage: Wallet storage
            config: Optional Config (uses Config() if not provided)
            api_factory: Optional APIClientFactory; when provided, starts background
                MarketDataCollector so scan buttons return cached data immediately
        """
        self.app = Flask(__name__, template_folder=TEMPLATE_DIR)
        # Waitress/production mode defaults to template caching; keep HTML fresh on disk edits.
        self.app.config["TEMPLATES_AUTO_RELOAD"] = True
        self.app.jinja_env.auto_reload = True
        self.storage = storage
        self.config = config or Config()
        self.api_factory = api_factory
        self._api_factory_lazy = None
        self.collector = None
        # Session-level market cache shared across classify + vet calls (thread-safe, 2h TTL)
        import threading as _threading
        self._session_market_cache: dict = {}
        self._session_cache_lock = _threading.Lock()
        self._session_cache_ts: dict = {}  # mid -> float (time.time when fetched)
        if api_factory:
            from src.collector import MarketDataCollector
            interval = int(self.config.get("scan_interval_sec", 180) or 180)
            ttl = int(self.config.get("cache_ttl_sec", 0) or 0)
            self.collector = MarketDataCollector(
                storage=self.storage,
                config=self.config,
                api_factory=api_factory,
                interval_sec=max(30, min(3600, interval)),
                cache_ttl_sec=max(0, min(3600, ttl)),
            )
        self.require_auth = os.getenv("DASHBOARD_REQUIRE_AUTH", "false").lower() in (
            "true",
            "1",
            "t",
        )
        self.api_key = os.getenv("DASHBOARD_API_KEY")
        if self.require_auth and not (self.api_key or "").strip():
            logger.warning(
                "DASHBOARD_REQUIRE_AUTH is enabled but DASHBOARD_API_KEY is empty — requests will fail with 401"
            )
        elif not self.require_auth:
            logger.info(
                "Dashboard: open access (no API key). Optional hardening: set "
                "DASHBOARD_REQUIRE_AUTH=true and DASHBOARD_API_KEY for production."
            )

        self._register_collector_routes()

        @self.app.before_request
        def check_auth():
            if self.require_auth:
                if request.headers.get("X-API-KEY") != self.api_key:
                    abort(401)

        @self.app.after_request
        def add_no_cache(response):
            """Prevent browser/proxy caching so dashboard always shows fresh data."""
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        def _wallet_to_json_safe(w):
            """Convert wallet to JSON-serializable dict (handles datetime, bytes, etc)."""
            d = w.to_dict() if hasattr(w, "to_dict") else {}
            out = {}
            for k, v in d.items():
                if v is None:
                    out[k] = None
                elif hasattr(v, "isoformat"):
                    out[k] = v.isoformat()
                elif isinstance(v, (bytes, bytearray)):
                    out[k] = v.decode("utf-8", errors="replace")
                elif isinstance(v, (dict, list, str, int, float, bool)):
                    out[k] = v
                else:
                    out[k] = str(v)
            # Specialty: keep flag consistent with category (fixes stale is_specialty=0 in DB)
            cat = (out.get("specialty_category") or "").strip()
            if cat:
                out["is_specialty"] = True
            else:
                out["is_specialty"] = bool(
                    out.get("is_specialty") in (True, 1, "1")
                )
            return out

        @self.app.route("/")
        def index():
            try:
                self.config.reload()
            except Exception as e:
                logger.warning("config reload (index): %s", e)
            try:
                wallets = self.storage.list_wallets()
            except Exception as e:
                logger.exception("list_wallets error: %s", e)
                wallets = []

            try:
                raw = json.dumps([_wallet_to_json_safe(w) for w in wallets])
                wallets_json = raw.replace("</script>", "<\\/script>")
            except Exception as e:
                logger.exception("wallets_json serialize error: %s", e)
                wallets_json = "[]"

            stats = self._calculate_stats(wallets)
            health = self._get_system_health()
            user_count = self._get_user_count()
            settings = self._get_settings()

            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            resp = make_response(render_template(
                "index.html",
                wallets=wallets,
                wallets_json=wallets_json,
                stats=stats,
                health=health,
                user_count=user_count,
                settings=settings,
                project_root=project_root,
            ))
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            return resp

        @self.app.route("/api/stats")
        def api_stats():
            """Get real-time statistics."""
            wallets = self.storage.list_wallets()
            return jsonify(self._calculate_stats(wallets))

        @self.app.route("/api/health")
        def api_health():
            """Get system health status. ?accurate=1 uses longer CPU sampling for accuracy."""
            accurate = request.args.get("accurate", "").lower() in ("1", "true", "yes")
            return jsonify(self._get_system_health(accurate=accurate))

        @self.app.route("/api/settings", methods=["GET", "POST"])
        def api_settings():
            """Get or update settings."""
            if request.method == "GET":
                try:
                    self.config.reload()
                except Exception as e:
                    logger.warning("config reload (api_settings): %s", e)
            if request.method == "POST":
                data = request.get_json() or {}
                for k, v in data.items():
                    self.config.set(k, v)
                try:
                    self.config.save()
                except Exception as e:
                    logger.warning("config save error: %s", e)
                return jsonify({"ok": True, "message": "Settings updated"})
            return jsonify(self._get_settings())

        @self.app.route("/api/dashboard/data")
        def api_dashboard_data():
            """Return all dashboard data as JSON for reliable loading."""
            try:
                self.config.reload()
            except Exception as e:
                logger.warning("config reload (api_dashboard_data): %s", e)
            try:
                wallets = self.storage.list_wallets()
                wallets_json = [_wallet_to_json_safe(w) for w in wallets]
                stats = self._calculate_stats(wallets)
                return jsonify({
                    "wallets": wallets_json,
                    "stats": stats,
                    "health": self._get_system_health(),
                    "user_count": self._get_user_count(),
                    "settings": self._get_settings(),
                })
            except Exception as e:
                logger.exception("api_dashboard_data error: %s", e)
                return jsonify({"wallets": [], "stats": {}, "health": {}, "user_count": {}, "settings": {}})

        @self.app.route("/api/wallets")
        def api_wallets():
            """Get all wallets."""
            try:
                wallets = self.storage.list_wallets()
                return jsonify([_wallet_to_json_safe(w) for w in wallets])
            except Exception as e:
                logger.exception("api_wallets error: %s", e)
                return jsonify([])

        @self.app.route("/api/wallet/<address>")
        def api_wallet(address):
            """Get specific wallet details."""
            wallet = self.storage.get_wallet(address)
            if not wallet:
                return jsonify({"error": "Wallet not found"}), 404
            return jsonify(wallet.to_dict())

        @self.app.route("/api/wallet/<address>/positions")
        def api_wallet_positions(address):
            """Get wallet positions."""
            # This would connect to the API to get actual positions
            return jsonify([])

        @self.app.route("/api/wallet/<address>/history")
        def api_wallet_history(address):
            """Get wallet trade history."""
            return jsonify([])

        @self.app.route("/api/alerts")
        def api_alerts():
            """Get recent alerts (from collector when run mode)."""
            alerts = []
            if self.collector:
                alerts = self.collector.get_recent_alerts(limit=50)
            resp = jsonify([{**a, "ts": a["ts"]} for a in alerts])
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp

        @self.app.route("/api/convergence/check")
        def api_convergence_check():
            """Standalone convergence check — finds markets where 2+ high-performers overlap."""
            force = request.args.get("force") in ("1", "true", "yes")
            if self.collector and not force:
                cached = self.collector.get_cached("convergence", force_fresh=force)
                if cached:
                    out = {k: v for k, v in cached.items() if k != "ts"}
                    out["cached"] = True
                    out["cached_at"] = datetime.fromtimestamp(cached.get("ts", 0)).isoformat() if cached.get("ts") else None
                    return jsonify(out)
            try:
                from src.core import DetectorFactory, ScanPipeline
                from src.market.api import APIClientFactory
                api_factory = APIClientFactory(self.config)
                factory = DetectorFactory(self.config, self.storage, api_factory)
                pipeline = ScanPipeline(factory)
                result = pipeline.run_convergence(min_wallets=2)
                return jsonify(result)
            except Exception as e:
                logger.exception("convergence check error: %s", e)
                return jsonify({"ok": False, "error": str(e), "convergences": [], "count": 0})

        @self.app.route("/api/insider/scan")
        def api_insider_scan():
            """Scan for insider/whale signals (large trade + fresh wallet + winning outcome)."""
            force = request.args.get("force") in ("1", "true", "yes")
            if self.collector and not force:
                cached = self.collector.get_cached("insider", force_fresh=force)
                if cached:
                    out = {k: v for k, v in cached.items() if k != "ts"}
                    out["cached"] = True
                    out["cached_at"] = datetime.fromtimestamp(cached.get("ts", 0)).isoformat() if cached.get("ts") else None
                    return jsonify(out)
            try:
                from src.core import DetectorFactory, ScanPipeline
                from src.market.api import APIClientFactory
                api_factory = APIClientFactory(self.config)
                factory = DetectorFactory(self.config, self.storage, api_factory)
                pipeline = ScanPipeline(factory)
                result = pipeline.run_insider(limit=10, apply_noise_filters=False)
                return jsonify(result)
            except Exception as e:
                logger.exception("insider scan error: %s", e)
                import traceback
                traceback.print_exc()
                return jsonify({"ok": False, "error": str(e), "signals": [], "count": 0})

        @self.app.route("/api/contrarian/scan")
        def api_contrarian_scan():
            """Scan for contrarian opportunities (crowd on one side, high payout on minority)."""
            force = request.args.get("force") in ("1", "true", "yes")
            if self.collector and not force:
                cached = self.collector.get_cached("contrarian", force_fresh=force)
                if cached:
                    out = {k: v for k, v in cached.items() if k != "ts"}
                    out["cached"] = True
                    out["cached_at"] = datetime.fromtimestamp(cached.get("ts", 0)).isoformat() if cached.get("ts") else None
                    return jsonify(out)
            try:
                from src.core import DetectorFactory, ScanPipeline
                from src.market.api import APIClientFactory
                api_factory = APIClientFactory(self.config)
                factory = DetectorFactory(self.config, self.storage, api_factory)
                pipeline = ScanPipeline(factory)
                result = pipeline.run_contrarian()
                return jsonify(result)
            except Exception as e:
                logger.exception("contrarian scan error: %s", e)
                return jsonify({"ok": False, "error": str(e), "signals": [], "count": 0})

        @self.app.route("/api/strategy/metrics")
        def api_strategy_metrics():
            """Strategy scan metrics for analytics (runs, avg signals per scan)."""
            hours = int(request.args.get("hours", 24))
            hours = max(1, min(168, hours))
            try:
                from src.analytics.scan_results_storage import ScanResultsStorage
                storage = ScanResultsStorage()
                metrics = {
                    "insider": storage.get_metrics("insider", hours),
                    "convergence": storage.get_metrics("convergence", hours),
                    "contrarian": storage.get_metrics("contrarian", hours),
                }
                return jsonify({"ok": True, "hours": hours, "metrics": metrics})
            except Exception as e:
                logger.exception("strategy metrics error: %s", e)
                return jsonify({"ok": False, "error": str(e), "metrics": {}})

        @self.app.route("/api/alerts/send", methods=["POST"])
        def api_send_alert():
            """Send a test alert."""
            data = request.get_json()
            alert_type = data.get("type")
            message = data.get("message")
            # Alert sending logic here
            return jsonify({"ok": True, "message": f"Alert sent: {message}"})

        @self.app.route("/api/users")
        def api_users():
            """Get user count and details."""
            return jsonify(self._get_user_count())

        @self.app.route("/api/markets/active")
        def api_active_markets():
            """Get active markets."""
            return jsonify([])

        @self.app.route("/api/markets/resolved")
        def api_resolved_markets():
            """Get resolved markets."""
            return jsonify([])

        @self.app.route("/api/outcomes")
        def api_outcomes():
            """Get outcome statistics."""
            return jsonify(
                {"total_yes": 0, "total_no": 0, "avg_yes_price": 0, "avg_no_price": 0}
            )

        @self.app.route("/api/telegram/test", methods=["POST"])
        def api_test_telegram():
            """Send test Telegram message."""
            return jsonify({"ok": True, "message": "Test message sent"})

        @self.app.route("/api/discord/test", methods=["POST"])
        def api_test_discord():
            """Send test Discord message."""
            return jsonify({"ok": True, "message": "Test message sent"})

        @self.app.route("/api/exchange/add", methods=["POST"])
        def api_add_exchange():
            """Add exchange connection."""
            data = request.get_json()
            exchange = data.get("exchange")
            return jsonify({"ok": True, "message": f"{exchange} added"})

        @self.app.route("/api/exchange/remove", methods=["POST"])
        def api_remove_exchange():
            """Remove exchange connection."""
            data = request.get_json()
            exchange = data.get("exchange")
            return jsonify({"ok": True, "message": f"{exchange} removed"})

        @self.app.route("/api/exchange/list")
        def api_list_exchanges():
            """List connected exchanges."""
            return jsonify([])

        @self.app.route("/api/wallet/add", methods=["POST"])
        def api_add_wallet():
            """Add a new wallet to track."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400
            data = request.get_json() or {}
            address = (data.get("address") or "").strip()
            nickname = (data.get("nickname") or "").strip() or _generate_random_nickname()
            if not address:
                return jsonify({"error": "Address required"}), 400
            from src.utils import is_valid_address
            if not is_valid_address(address):
                return jsonify({"error": "Invalid address format"}), 400
            cap = max_tracked_wallets(self.config)
            if len(self.storage.list_wallets()) >= cap:
                return jsonify({
                    "error": f"Maximum {cap} wallets tracked (wallet_discovery_max_wallets). Remove one first.",
                }), 400
            try:
                wallet_obj = Wallet(address=address, nickname=nickname)
                added = self.storage.add_wallet(wallet_obj)
                if not added:
                    return jsonify({"error": "Wallet already exists"}), 400
                return jsonify({"ok": True, "wallet": _wallet_to_json_safe(wallet_obj)})
            except Exception as e:
                return jsonify({"error": str(e)}), 400

        @self.app.route("/api/wallet/remove", methods=["POST"])
        def api_remove_wallet():
            """Remove a wallet from tracking."""
            data = request.get_json()
            address = data.get("address")
            try:
                self.storage.remove_wallet(address)
                return jsonify({"ok": True, "message": "Wallet removed"})
            except Exception as e:
                return jsonify({"error": str(e)}), 400

        @self.app.route("/api/wallet/vet", methods=["POST"])
        def api_vet_wallet():
            """Vet a wallet: run WalletVetting and persist results."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400
            data = request.get_json() or {}
            address = (data.get("address") or "").strip().lower()
            if not address:
                return jsonify({"error": "Address required"}), 400
            try:
                from src.wallet.vetting import WalletVetting
                from src.utils import is_valid_address
                if not is_valid_address(address):
                    return jsonify({"error": "Invalid address format"}), 400
                api = self._get_api_factory()
                vetter = WalletVetting(api, config=self.config)
                result = vetter.vet_wallet(address, min_bet=10, platform="polymarket")
                if not result:
                    return jsonify({"ok": False, "error": "No trades found or vetting failed"})
                passed = result.get("passed", False)
                new_tier = "vetted" if passed else "watch"
                self.storage.update_wallet_vetting(
                    address,
                    bot_score=result.get("bot_score"),
                    unresolved_exposure_usd=None,
                    total_pnl=result.get("total_pnl"),
                    roi_pct=result.get("roi_pct"),
                    conviction_score=result.get("conviction_score"),
                    is_specialty=result.get("is_specialty", False),
                    specialty_note=result.get("specialty_note"),
                    specialty_market_id=result.get("specialty_market_id"),
                    specialty_category=result.get("specialty_category"),
                    specialty_roi_pct=result.get("specialty_roi_pct"),
                    is_win_streak_badge=result.get("is_win_streak_badge", False),
                    tier=new_tier,
                    total_trades=result.get("total_trades"),
                    wins=result.get("total_wins"),
                    win_rate=result.get("win_rate_real"),
                    trade_volume=result.get("total_volume"),
                )
                status = "Passed" if passed else "Did not pass"
                issues = result.get("issues") or []
                return jsonify({
                    "ok": True,
                    "passed": passed,
                    "tier": new_tier,
                    "message": f"Vetted {address[:12]}... — {status}. Vet never removes wallets; it updates tier and specialty.",
                    "win_rate": result.get("win_rate_real"),
                    "total_pnl": result.get("total_pnl"),
                    "bot_score": result.get("bot_score"),
                    "specialty_category": result.get("specialty_category"),
                    "specialty_roi_pct": result.get("specialty_roi_pct"),
                    "is_specialty": bool(result.get("is_specialty")),
                    "specialty_note": result.get("specialty_note"),
                    "issues": issues[:12],
                    "issues_count": len(issues),
                })
            except Exception as e:
                logger.exception("vet error: %s", e)
                import traceback
                traceback.print_exc()
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/import/leaderboard", methods=["POST"])
        def api_import_leaderboard():
            """Import from leaderboard."""
            try:
                from src.wallet import Wallet
                from src.market.leaderboard import LeaderboardImporter
                data = request.get_json() or {}
                limit = int(data.get("limit", 10))
                api = self._get_api_factory()
                importer = LeaderboardImporter(api)
                traders = importer.import_all_polymarket(limit=limit)
                added, skipped, omitted_due_to_cap = 0, 0, 0
                cap = max_tracked_wallets(self.config)
                tlist = traders or []
                for i, trader in enumerate(tlist, 1):
                    if len(self.storage.list_wallets()) >= cap:
                        omitted_due_to_cap = len(tlist) - i + 1
                        break
                    w = Wallet(address=trader["address"], nickname=trader.get("username", f"Trader{i}"))
                    if self.storage.add_wallet(w):
                        added += 1
                    else:
                        skipped += 1
                return jsonify({
                    "ok": True,
                    "added": added,
                    "skipped": skipped,
                    "omitted_due_to_cap": omitted_due_to_cap,
                    "total": len(tlist),
                })
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/refresh/wallets", methods=["POST"])
        def api_refresh_wallets():
            """Refresh all wallet data."""
            try:
                from src.wallet.calculator import WalletCalculator
                data = request.get_json() or {}
                address = (data.get("address") or "all").strip().lower()
                api = self._get_api_factory()
                calculator = WalletCalculator(api)
                wallets = self.storage.list_wallets()
                if not wallets:
                    return jsonify({"ok": True, "message": "No wallets to refresh", "updated": 0})
                updated = 0
                for w in wallets:
                    if address != "all" and w.address.lower() != address:
                        continue
                    (
                        total_trades,
                        wins,
                        win_rate,
                        total_volume,
                        _rn,
                    ) = calculator.calculate_wallet_stats(w.address)
                    self.storage.update_wallet_stats(
                        w.address,
                        total_trades,
                        wins,
                        total_volume,
                        win_rate=win_rate,
                    )
                    if total_trades > 0:
                        self.storage.log_wallet_history(w)
                    updated += 1
                return jsonify({"ok": True, "message": f"Refreshed {updated} wallet(s)", "updated": updated})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/check")
        def api_command_check():
            """Check convergences."""
            try:
                from src.alerts.convergence import ConvergenceDetector
                api = self._get_api_factory()
                detector = ConvergenceDetector(
                    wallet_storage=self.storage,
                    threshold=float(self.config.get("win_rate_threshold", 55) or 55),
                    min_trades=int(self.config.get("min_trades_for_high_performer", 10) or 10),
                    api_factory=api,
                    min_market_volume=float(self.config.get("convergence_min_volume", 5000) or 5000),
                )
                convergences = detector.find_convergences(min_wallets=2)
                out = []
                for c in convergences or []:
                    m = c.get("market_info") or {}
                    wl = c.get("wallets", [])
                    out.append({"market": m.get("question", "Unknown"), "wallets": wl, "market_id": c.get("market_id")})
                return jsonify({"ok": True, "convergences": out})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/markets")
        def api_command_markets():
            """List active markets."""
            try:
                api = self._get_api_factory()
                polymarket = api.get_polymarket_api()
                limit = int(request.args.get("limit", 20))
                markets = polymarket.get_active_markets(limit=limit)
                out = [{"question": m.get("question", "Unknown"), "volume": m.get("volume", 0), "id": m.get("id")} for m in (markets or [])]
                return jsonify({"ok": True, "markets": out})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/portfolio")
        def api_command_portfolio():
            """Show portfolio for address."""
            try:
                address = (request.args.get("address") or "").strip()
                if not address:
                    return jsonify({"ok": False, "error": "address required"}), 400
                api = self._get_api_factory()
                portfolio = self.storage.get_portfolio(address, api)
                if not portfolio:
                    return jsonify({"ok": False, "error": "Wallet not found"}), 404
                positions = [{"market": p.market, "outcome": p.outcome, "shares": p.shares, "value": p.value} for p in (portfolio.positions or [])]
                return jsonify({"ok": True, "nickname": portfolio.nickname, "address": portfolio.address, "total_value": portfolio.total_value, "positions": positions})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/history")
        def api_command_history():
            """Show performance history for address."""
            try:
                address = (request.args.get("address") or "").strip()
                if not address:
                    return jsonify({"ok": False, "error": "address required"}), 400
                history = self.storage.get_wallet_history(address)
                return jsonify({"ok": True, "history": history or []})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/smart-money")
        def api_command_smart_money():
            """Identify smart money wallets."""
            try:
                from src.analytics.smart_money import SmartMoneyDetector
                api = self._get_api_factory()
                detector = SmartMoneyDetector(api)
                wallets = detector.identify_smart_money()
                return jsonify({"ok": True, "wallets": wallets or []})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/signals")
        def api_command_signals():
            """Generate trading signals (convergence, insider, contrarian, wallet)."""
            try:
                from src.analytics.signals import SignalGenerator
                api = self._get_api_factory()
                generator = SignalGenerator(
                    storage=self.storage,
                    api_factory=api,
                    config=self.config,
                )
                signals = generator.generate_signals()
                return jsonify({"ok": True, "signals": signals or []})
            except (ImportError, AttributeError):
                return jsonify({"ok": True, "signals": [], "message": "SignalGenerator not implemented"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/check_positions")
        def api_command_check_positions():
            """Check for position changes."""
            try:
                from src.alerts.position import PositionAlerter
                alerter = PositionAlerter()
                wallets = self.storage.list_wallets()
                alerter.check_positions(wallets)
                return jsonify({"ok": True, "message": "Checked for position changes"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/check_odds")
        def api_command_check_odds():
            """Check odds movement."""
            try:
                from src.alerts.odds import OddsAlerter
                alerter = OddsAlerter()
                alerter.check_odds([])
                return jsonify({"ok": True, "message": "Checked for odds movement"})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/command/jupiter-quote", methods=["POST"])
        def api_command_jupiter_quote():
            """Jupiter quote (input-mint, output-mint, amount)."""
            try:
                data = request.get_json() or {}
                inp = (data.get("input_mint") or data.get("input-mint") or "").strip()
                out = (data.get("output_mint") or data.get("output-mint") or "").strip()
                amount = data.get("amount")
                if not inp or not out or amount is None:
                    return jsonify({"ok": False, "error": "input_mint, output_mint, amount required"}), 400
                api = self._get_api_factory()
                jupiter = api.get_jupiter_client()
                quote = jupiter.get_quote(inp, out, int(amount))
                return jsonify({"ok": True, "quote": quote})
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/export/wallets")
        def api_export_wallets():
            """Export wallets data."""
            wallets = self.storage.list_wallets()
            return jsonify([w.to_dict() for w in wallets])

        @self.app.route("/api/polymarket/store-credentials", methods=["POST"])
        def store_polymarket_credentials():
            """Store Polymarket API credentials."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json()
            user_id = data.get("user_id")
            api_key = data.get("api_key")
            api_secret = data.get("api_secret")
            api_passphrase = data.get("api_passphrase")

            if not all([user_id, api_key, api_secret, api_passphrase]):
                return jsonify({"error": "Missing required fields"}), 400

            try:
                store_credentials(
                    user_id=user_id,
                    platform="polymarket",
                    creds={
                        "api_key": api_key,
                        "api_secret": api_secret,
                        "api_passphrase": api_passphrase,
                    },
                )
                return jsonify({"ok": True, "message": "Credentials saved"}), 200
            except Exception as e:
                logger.warning("Error storing Polymarket credentials: %s", e)
                return jsonify({"error": "Failed to store credentials"}), 500

        @self.app.route("/api/kalshi/store-credentials", methods=["POST"])
        def store_kalshi_credentials():
            """Store Kalshi API credentials."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json()
            user_id = data.get("user_id")
            api_key_id = data.get("api_key_id")
            private_key_pem = data.get("private_key_pem")

            if not all([user_id, api_key_id, private_key_pem]):
                return jsonify({"error": "Missing required fields"}), 400

            try:
                store_credentials(
                    user_id=user_id,
                    platform="kalshi",
                    creds={
                        "api_key_id": api_key_id,
                        "private_key_pem": private_key_pem,
                    },
                )
                return jsonify({"ok": True, "message": "Credentials saved"}), 200
            except Exception as e:
                logger.warning("Error storing Kalshi credentials: %s", e)
                return jsonify({"error": "Failed to store credentials"}), 500

        # ============ BULK WALLET IMPORT ============
        @self.app.route("/api/wallets/bulk-import", methods=["POST"])
        def bulk_import_wallets():
            """Bulk import wallets from text/CSV. Data stored via WalletStorage.add_wallet."""
            import re
            from src.utils import is_valid_address

            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json() or {}
            raw = data.get("wallets", "")
            # Handle both string (newline-separated) and list of addresses
            if isinstance(raw, list):
                wallets_text = "\n".join(str(x) for x in raw)
            else:
                wallets_text = str(raw or "").strip()

            if not wallets_text:
                return jsonify({"error": "No wallets provided"}), 400

            imported = []
            errors = []
            address_pattern = re.compile(r"0x[a-fA-F0-9]{40}")
            NULL_ADDR = "0x0000000000000000000000000000000000000000"

            for line in wallets_text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                addresses = address_pattern.findall(line)

                if not addresses:
                    parts = [p.strip() for p in line.split(",")]
                    for part in parts:
                        if part and address_pattern.fullmatch(part):
                            addresses.append(part)
                            break

                if not addresses:
                    errors.append(f"Could not find address in: {line}")
                    continue

                # Nickname: from comma-separated non-address part, or rest of line after address
                def get_nickname(addr, ln):
                    for part in ln.split(","):
                        part = part.strip()
                        if part and part != addr and not address_pattern.fullmatch(part):
                            return part
                    idx = ln.find(addr)
                    if idx >= 0:
                        rest = ln[idx + len(addr) :].strip().strip(",").strip()
                        if rest:
                            return rest
                    return None  # No nickname found; caller will use random

                for address in addresses:
                    addr_normalized = address.lower()
                    if addr_normalized == NULL_ADDR.lower():
                        errors.append(f"Invalid (null) address: {address}")
                        continue
                    if not is_valid_address(address):
                        errors.append(f"Invalid address format: {address}")
                        continue

                    nickname = get_nickname(address, line)
                    if not nickname or len(nickname) > 64:
                        nickname = _generate_random_nickname()

                    try:
                        cap = max_tracked_wallets(self.config)
                        if len(self.storage.list_wallets()) >= cap:
                            errors.append(
                                f"At wallet cap ({cap}, wallet_discovery_max_wallets); remove wallets or raise the cap."
                            )
                            break
                        wallet_obj = Wallet(address=addr_normalized, nickname=nickname)
                        result = self.storage.add_wallet(wallet_obj)
                        if result:
                            imported.append(
                                {"address": addr_normalized, "nickname": nickname, "added": True}
                            )
                        else:
                            errors.append(f"Wallet already exists: {addr_normalized}")
                    except Exception as e:
                        errors.append(f"Failed to add {addr_normalized}: {str(e)}")

            return jsonify(
                {
                    "ok": True,
                    "imported": imported,
                    "imported_count": len(imported),
                    "errors": errors,
                    "error_count": len(errors),
                    "auto_vet_triggered": data.get("auto_vet", False),
                }
            )

        @self.app.route("/api/wallets/analyze", methods=["POST"])
        def analyze_wallets():
            """Analyze and classify multiple wallets using WalletClassifier."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json()
            addresses = data.get("addresses", [])

            if not addresses:
                return jsonify({"error": "No addresses provided"}), 400

            api_factory = APIClientFactory(self.config)
            polymarket_api = api_factory.get_polymarket_api()
            classifier = WalletClassifier(polymarket_api)

            trade_limit = int(data.get("trade_limit", 350) or 350)
            trade_limit = max(50, min(trade_limit, 500))

            # Reuse market cache across wallets AND across classify/vet requests (session-level)
            shared_market_cache: dict = self._get_shared_market_cache()
            results = []
            for addr in addresses[:25]:
                addr = (addr or "").strip().lower()
                if not addr:
                    continue
                try:
                    trades = polymarket_api.get_wallet_trades(
                        addr, limit=trade_limit
                    )
                    if not trades:
                        results.append(
                            {
                                "address": addr,
                                "score": 0,
                                "classification": "no_trades",
                                "reason": "No trades found for this wallet",
                            }
                        )
                        continue

                    existing = self.storage.get_wallet(addr)
                    score = classifier.classify_wallet(
                        addr,
                        trades,
                        existing_wallet=existing,
                        market_cache=shared_market_cache,
                    )
                    reason = classifier.get_classification_reason(score)

                    results.append(
                        {
                            "address": addr,
                            "score": round(score.total_score, 1),
                            "classification": score.classification.value,
                            "reason": reason,
                            "is_bot": score.is_bot,
                            "is_farmer": score.is_farmer,
                            "is_high_loss_rate": score.is_high_loss_rate,
                            "current_win_streak": score.current_win_streak,
                            "max_win_streak": score.max_win_streak,
                            "win_rate": round(score.win_rate, 1),
                            "total_trades": score.total_trades,
                            "total_volume": round(score.total_volume, 2),
                            "stats_7d": {
                                "trades": score.stats_7d.total_trades
                                if score.stats_7d
                                else 0,
                                "win_rate": round(score.stats_7d.win_rate, 1)
                                if score.stats_7d
                                else 0,
                                "volume": round(score.stats_7d.total_volume, 2)
                                if score.stats_7d
                                else 0,
                            }
                            if score.stats_7d
                            else None,
                            "stats_14d": {
                                "trades": score.stats_14d.total_trades
                                if score.stats_14d
                                else 0,
                                "win_rate": round(score.stats_14d.win_rate, 1)
                                if score.stats_14d
                                else 0,
                                "volume": round(score.stats_14d.total_volume, 2)
                                if score.stats_14d
                                else 0,
                            }
                            if score.stats_14d
                            else None,
                            "tier": getattr(score, "tier", None),
                            "is_specialty": bool(
                                getattr(score, "specialty_category", None)
                            ),
                            "specialty_category": getattr(
                                score, "specialty_category", None
                            ),
                            "specialty_win_rate": round(
                                float(getattr(score, "specialty_win_rate", 0) or 0),
                                1,
                            ),
                            "specialty_volume": round(
                                float(getattr(score, "specialty_volume", 0) or 0),
                                2,
                            ),
                            "specialty_category_2": getattr(
                                score, "specialty_category_2", None
                            ),
                        }
                    )

                    # Persist: create wallet if new, then update with classification
                    if not existing:
                        cap_an = max_tracked_wallets(self.config)
                        if len(self.storage.list_wallets()) >= cap_an:
                            results[-1]["persist_skipped_cap"] = True
                            results[-1]["persist_note"] = (
                                f"Analysis only: maximum {cap_an} wallets tracked "
                                "(wallet_discovery_max_wallets)."
                            )
                            existing = None
                        else:
                            existing = Wallet(
                                address=addr, nickname=_generate_random_nickname()
                            )
                            self.storage.add_wallet(existing)
                            existing = self.storage.get_wallet(addr)
                    if existing:
                        try:
                            from src.wallet.classifier import WalletClassification

                            if not (getattr(existing, "nickname", "") or "").strip():
                                existing.nickname = _generate_random_nickname()
                            existing.classification = (
                                score.classification.value
                                if score.classification
                                else None
                            )
                            existing.classification_reason = reason
                            existing.total_score = score.total_score
                            existing.total_trades = int(score.total_trades or 0)
                            existing.wins = int(score.wins or 0)
                            existing.win_rate = float(score.win_rate or 0)
                            existing.trade_volume = int(round(float(score.total_volume or 0)))
                            if getattr(score, "total_pnl", None) is not None:
                                existing.total_pnl = float(score.total_pnl)
                            existing.is_bot = score.is_bot
                            existing.is_farmer = score.is_farmer
                            existing.is_high_loss_rate = score.is_high_loss_rate
                            existing.current_win_streak = score.current_win_streak
                            existing.max_win_streak = score.max_win_streak
                            existing.consecutive_losses = getattr(
                                score, "consecutive_losses", 0
                            )
                            existing.max_consecutive_losses = getattr(
                                score, "max_consecutive_losses", 0
                            )
                            existing.tier = score.tier
                            existing.score_7d = getattr(score, "score_7d", 0)
                            existing.score_14d = getattr(score, "score_14d", 0)
                            existing.last_scored_at = datetime.now().isoformat()
                            existing.is_specialty = bool(getattr(score, "specialty_category", None))
                            existing.specialty_category = getattr(score, "specialty_category", None)
                            existing.specialty_roi_pct = getattr(score, "specialty_roi_pct", None)
                            # Smart money: GOOD/EXCELLENT/WIN_STREAK, not bot/farmer
                            good_classes = (
                                WalletClassification.GOOD,
                                WalletClassification.EXCELLENT,
                                WalletClassification.WIN_STREAK,
                            )
                            existing.is_smart_money = (
                                score.classification in good_classes
                                and not score.is_bot
                                and not score.is_farmer
                            )
                            # Specialty: has dominant category from classifier
                            existing.is_specialty = bool(
                                getattr(score, "specialty_category", None)
                            )
                            if getattr(score, "specialty_category", None):
                                existing.specialty_category = score.specialty_category
                            existing.specialty_win_rate = float(
                                getattr(score, "specialty_win_rate", 0) or 0
                            )
                            existing.specialty_volume = float(
                                getattr(score, "specialty_volume", 0) or 0
                            )
                            existing.specialty_category_2 = getattr(
                                score, "specialty_category_2", None
                            )
                            # Win streak badge: max_win_streak >= threshold
                            existing.is_win_streak_badge = (
                                getattr(score, "max_win_streak", 0) or 0
                            ) >= self.config.get("win_streak_badge_threshold", 5)
                            self.storage.update_wallet(existing)
                        except Exception as update_err:
                            logger.warning(
                                "Error updating wallet %s: %s", addr, update_err
                            )

                except Exception as e:
                    results.append(
                        {
                            "address": addr,
                            "score": 0,
                            "classification": "error",
                            "reason": str(e),
                        }
                    )

            return jsonify(
                {
                    "ok": True,
                    "results": results,
                    "total": len(addresses),
                    "analyzed": len(results),
                    "batch_max": 25,
                    "trade_limit": trade_limit,
                }
            )

        @self.app.route("/api/wallets/bulk-vet", methods=["POST"])
        def bulk_vet_wallets():
            """Vet multiple wallets sequentially and return summary."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json()
            addresses = data.get("addresses", [])
            if not addresses:
                return jsonify({"ok": False, "error": "No addresses provided"}), 400

            addresses = [(a or "").strip().lower() for a in addresses if (a or "").strip()]
            if not addresses:
                return jsonify({"ok": False, "error": "No valid addresses"}), 400

            try:
                from src.wallet.vetting import WalletVetting
                from src.utils import is_valid_address

                api = self._get_api_factory()
                # Single vetter instance + shared session cache for the whole bulk run
                vetter = WalletVetting(api, config=self.config)
                shared_market_cache = self._get_shared_market_cache()
                passed_count = 0
                failed_count = 0
                errors = []

                for addr in addresses:
                    if not is_valid_address(addr):
                        errors.append(f"{addr[:12]}... invalid")
                        failed_count += 1
                        continue
                    try:
                        existing_w = self.storage.get_wallet(addr)
                        lb_cat = getattr(existing_w, "specialty_category", None) if existing_w else None
                        result = vetter.vet_wallet(addr, min_bet=10, platform="polymarket",
                                                   market_cache=shared_market_cache,
                                                   leaderboard_category=lb_cat)
                        if not result:
                            failed_count += 1
                            errors.append(f"{addr[:12]}... no trades")
                            continue
                        p = result.get("passed", False)
                        if p:
                            passed_count += 1
                        else:
                            failed_count += 1
                        new_tier = "vetted" if p else "watch"
                        self.storage.update_wallet_vetting(
                            addr,
                            bot_score=result.get("bot_score"),
                            unresolved_exposure_usd=None,
                            total_pnl=result.get("total_pnl"),
                            roi_pct=result.get("roi_pct"),
                            conviction_score=result.get("conviction_score"),
                            is_specialty=bool(result.get("is_specialty"))
                            or bool((result.get("specialty_category") or "").strip()),
                            specialty_note=result.get("specialty_note"),
                            specialty_market_id=result.get("specialty_market_id"),
                            specialty_category=result.get("specialty_category"),
                            specialty_roi_pct=result.get("specialty_roi_pct"),
                            is_win_streak_badge=result.get("is_win_streak_badge", False),
                            tier=new_tier,
                            total_trades=result.get("total_trades"),
                            wins=result.get("total_wins"),
                            win_rate=result.get("win_rate_real"),
                            trade_volume=result.get("total_volume"),
                        )
                    except Exception as e:
                        failed_count += 1
                        errors.append(f"{addr[:12]}... {str(e)[:40]}")

                return jsonify({
                    "ok": True,
                    "total": len(addresses),
                    "passed": passed_count,
                    "failed": failed_count,
                    "message": f"Vetted {len(addresses)} wallet(s): {passed_count} passed, {failed_count} did not pass",
                    "errors": errors[:10],
                })
            except Exception as e:
                logger.exception("bulk vet error: %s", e)
                import traceback
                traceback.print_exc()
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/api/wallets/filter", methods=["POST"])
        def filter_wallets():
            """Filter wallets by criteria."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json()
            criteria = data.get("criteria", {})
            wallets = self.storage.list_wallets()

            filtered = []
            for w in wallets:
                include = True

                # Tier filter (only when tier is non-empty)
                if criteria.get("tier"):
                    if w.tier != criteria["tier"]:
                        include = False

                if "min_trades" in criteria:
                    if w.total_trades < criteria["min_trades"]:
                        include = False

                if "min_win_rate" in criteria:
                    if w.win_rate < criteria["min_win_rate"]:
                        include = False

                if "max_loss_rate" in criteria:
                    loss_rate = 100 - w.win_rate
                    if loss_rate > criteria["max_loss_rate"]:
                        include = False

                if criteria.get("smart_money_only"):
                    if not w.is_smart_money:
                        include = False

                if "classification" in criteria:
                    if w.classification != criteria["classification"]:
                        include = False

                if "exclude_bots" in criteria and criteria["exclude_bots"]:
                    if w.is_bot:
                        include = False

                if "exclude_farmers" in criteria and criteria["exclude_farmers"]:
                    if w.is_farmer:
                        include = False

                if (
                    "exclude_high_loss_rate" in criteria
                    and criteria["exclude_high_loss_rate"]
                ):
                    if w.is_high_loss_rate:
                        include = False

                if "min_score" in criteria:
                    if w.total_score < criteria["min_score"]:
                        include = False

                if "min_win_streak" in criteria:
                    if w.current_win_streak < criteria["min_win_streak"]:
                        include = False

                if "include_win_streak" in criteria and criteria["include_win_streak"]:
                    if not getattr(w, "is_win_streak_badge", False):
                        include = False

                if criteria.get("specialty_only"):
                    has_sp = bool(getattr(w, "is_specialty", False)) or bool(
                        (getattr(w, "specialty_category", None) or "").strip()
                    )
                    if not has_sp:
                        include = False

                if include:
                    filtered.append(_wallet_to_json_safe(w))

            total = len(wallets)
            return jsonify({"ok": True, "wallets": filtered, "count": len(filtered), "total": total})

        @self.app.route("/api/wallets/export")
        def export_wallets():
            """Export wallets."""
            wallets = self.storage.list_wallets()
            return jsonify(
                {
                    "ok": True,
                    "wallets": [w.to_dict() for w in wallets],
                    "count": len(wallets),
                }
            )

        # ============ TIER MANAGEMENT ============
        @self.app.route("/api/wallets/tiers", methods=["GET"])
        def get_wallets_by_tier():
            """Get wallets grouped by tier."""
            tier = request.args.get("tier", "all")
            if tier == "all":
                wallets = self.storage.list_wallets()
            else:
                wallets = self.storage.get_wallets_by_tier(tier)
            return jsonify(
                {
                    "ok": True,
                    "tier": tier,
                    "wallets": [w.to_dict() for w in wallets],
                    "count": len(wallets),
                }
            )

        @self.app.route("/api/wallets/<address>/tier", methods=["POST"])
        def change_wallet_tier(address):
            """Manually change wallet tier."""
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            data = request.get_json()
            new_tier = data.get("tier")
            reason = data.get("reason", "Manual change")

            if new_tier not in ["watch", "vetted", "elite"]:
                return jsonify(
                    {"error": "Invalid tier. Must be: watch, vetted, or elite"}
                ), 400

            success = self.storage.change_tier(address, new_tier, reason)
            return jsonify({"ok": success, "address": address, "new_tier": new_tier})

        @self.app.route("/api/wallets/<address>/patterns", methods=["GET"])
        def get_wallet_patterns(address):
            """Get pattern analysis for a wallet."""
            wallet = self.storage.get_wallet(address)
            if not wallet:
                return jsonify({"error": "Wallet not found"}), 404

            return jsonify(
                {
                    "ok": True,
                    "address": address,
                    "trading_hours": wallet.get_trading_hours_dict(),
                    "trading_days": wallet.get_trading_days_dict(),
                    "odds_distribution": wallet.get_odds_distribution_dict(),
                    "category_stats": wallet.get_category_stats(),
                    "preferred_odds_range": wallet.preferred_odds_range,
                    "size_consistency": wallet.size_consistency,
                    "avg_hold_duration_hours": wallet.avg_hold_duration_hours,
                }
            )

        @self.app.route("/api/wallets/<address>/tier-history", methods=["GET"])
        def get_tier_history(address):
            """Get tier change history for a wallet."""
            history = self.storage.get_tier_log(address)
            return jsonify({"ok": True, "history": history})

        @self.app.route("/api/wallets/<address>/scoring-history", methods=["GET"])
        def get_scoring_history(address):
            """Get scoring history for a wallet."""
            history = self.storage.get_scoring_history(address)
            return jsonify({"ok": True, "history": history})

        @self.app.route("/api/scoring/run", methods=["POST"])
        def run_scoring():
            """Run scoring on all wallets and update tiers."""
            from src.wallet.classifier import WalletClassifier
            from src.market.api import APIClientFactory

            api_factory = APIClientFactory(self.config)
            polymarket_api = api_factory.get_polymarket_api()
            classifier = WalletClassifier(polymarket_api)

            wallets = self.storage.get_all_wallets_with_scores()
            results = {"promoted": 0, "demoted": 0, "unchanged": 0}

            for wallet in wallets:
                try:
                    trades = polymarket_api.get_wallet_trades(wallet.address, limit=500)
                    if trades:
                        score = classifier.classify_wallet(wallet.address, trades)
                        old_tier = wallet.tier
                        new_tier = score.tier

                        if old_tier != new_tier:
                            self.storage.change_tier(
                                wallet.address,
                                new_tier,
                                f"Auto-update: score={score.total_score:.1f}",
                            )
                            if self._is_promotion(old_tier, new_tier):
                                results["promoted"] += 1
                            else:
                                results["demoted"] += 1
                        else:
                            results["unchanged"] += 1
                except Exception as e:
                    logger.warning("Scoring error for %s: %s", wallet.address, e)

            return jsonify({"ok": True, "results": results})

    def _get_api_factory(self):
        """Get or create APIClientFactory for command execution."""
        if self.api_factory:
            return self.api_factory
        if self._api_factory_lazy is None:
            self._api_factory_lazy = APIClientFactory(self.config)
        return self._api_factory_lazy

    def _is_promotion(self, old_tier: str, new_tier: str) -> bool:
        """Check if tier change is a promotion."""
        tier_order = {"watch": 0, "vetted": 1, "elite": 2}
        return tier_order.get(new_tier, 0) > tier_order.get(old_tier, 0)

    def _score_stats(self, stats):
        """Calculate score for time window stats."""
        if not stats or stats.total_trades == 0:
            return 0

        win_rate_score = stats.win_rate

        if stats.total_volume > 0:
            pnl_ratio = stats.total_pnl / stats.total_volume
            pnl_score = max(0, min(100, 50 + pnl_ratio * 500))
        else:
            pnl_score = 50

        pf_score = min(100, stats.profit_factor * 50) if stats.profit_factor > 0 else 0

        activity_score = 50
        if 1 <= stats.total_trades <= 50:
            activity_score = 100
        elif stats.total_trades > 50:
            activity_score = max(0, 100 - (stats.total_trades - 50) / 10)

        return (
            win_rate_score * 0.4
            + pnl_score * 0.3
            + pf_score * 0.2
            + activity_score * 0.1
        )

    @staticmethod
    def _safe_trade_volume(w):
        v = getattr(w, "trade_volume", None)
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _calculate_stats(self, wallets):
        """Calculate comprehensive statistics."""
        if not wallets:
            threshold = float(self.config.get("smart_money_threshold", 55) or 55)
            return {
                "total_wallets": 0,
                "smart_money_count": 0,
                "smart_money_threshold": threshold,
                "top_performer_min_trades": int(
                    self.config.get("min_trades_for_high_performer", 10) or 10
                ),
                "specialty_count": 0,
                "avg_win_rate": 0,
                "total_trades": 0,
                "total_wins": 0,
                "top_performers": 0,
                "avg_pnl": 0,
                "total_volume": 0,
                "vetted_volume": 0,
                "vetted_count": 0,
                "volume_display": 0,
                "volume_display_subtitle": "All tracked (no vetted yet)",
                "high_win_rate": 0,
                "medium_win_rate": 0,
                "low_win_rate": 0,
                "win_rate_distribution": [0, 0, 0, 0, 0],
            }

        total = len(wallets)
        threshold = float(self.config.get("smart_money_threshold", 55) or 55)
        min_trades = int(self.config.get("vet_min_trades_won", 5) or 5)
        min_high = int(self.config.get("min_trades_for_high_performer", 10) or 10)
        # Smart money: win_rate >= threshold, min trades, not bot/farmer/high_loss
        def _qualifies_smart_money(w):
            return (
                (w.win_rate or 0) >= threshold
                and (w.total_trades or 0) >= min_trades
                and not getattr(w, "is_bot", False)
                and not getattr(w, "is_farmer", False)
                and not getattr(w, "is_high_loss_rate", False)
            )

        smart_money = sum(1 for w in wallets if _qualifies_smart_money(w))
        # Specialty: is_specialty flag OR has specialty_category (from classifier)
        def _wallet_has_specialty(w):
            if getattr(w, "is_specialty", False):
                return True
            c = getattr(w, "specialty_category", None)
            return bool(c and str(c).strip())

        specialty = sum(1 for w in wallets if _wallet_has_specialty(w))
        avg_win = sum(w.win_rate or 0 for w in wallets) / total if total > 0 else 0
        total_trades = sum(w.total_trades or 0 for w in wallets)
        total_wins = sum(w.wins or 0 for w in wallets)
        # Top performers: stable cohort (not raw WR — that swings daily as trades settle)
        top_performers = sum(
            1
            for w in wallets
            if (w.win_rate or 0) >= threshold
            and (w.total_trades or 0) >= min_high
            and not getattr(w, "is_bot", False)
            and not getattr(w, "is_farmer", False)
        )
        total_pnl = sum(w.total_pnl or 0 for w in wallets)
        # Total volume: all tracked; vetted-only for header when any wallet is vetted
        total_volume = sum(self._safe_trade_volume(w) for w in wallets)
        vetted = [w for w in wallets if getattr(w, "tier", "watch") in ("vetted", "elite")]
        vetted_volume = sum(self._safe_trade_volume(w) for w in vetted)
        vetted_count = len(vetted)
        if vetted_count > 0:
            volume_display = vetted_volume
            volume_display_subtitle = "Vetted & elite wallets only"
        else:
            volume_display = total_volume
            volume_display_subtitle = "All tracked (no vetted wallets yet)"

        high_wr = sum(1 for w in wallets if (w.win_rate or 0) >= threshold)
        medium_wr = sum(1 for w in wallets if 40 <= (w.win_rate or 0) < threshold)
        low_wr = sum(1 for w in wallets if (w.win_rate or 0) < 40)

        # Distribution buckets (<20, 20-40, 40-threshold, threshold-70, >70)
        dist = [0, 0, 0, 0, 0]
        for w in wallets:
            wr = w.win_rate or 0
            if wr < 20:
                dist[0] += 1
            elif wr < 40:
                dist[1] += 1
            elif wr < threshold:
                dist[2] += 1
            elif wr < 70:
                dist[3] += 1
            else:
                dist[4] += 1

        return {
            "total_wallets": total,
            "smart_money_count": smart_money,
            "smart_money_threshold": threshold,
            "top_performer_min_trades": min_high,
            "specialty_count": specialty,
            "avg_win_rate": round(avg_win, 1),
            "total_trades": total_trades,
            "total_wins": total_wins,
            "top_performers": top_performers,
            "avg_pnl": round(total_pnl / total if total > 0 else 0, 2),
            "total_volume": total_volume,
            "vetted_volume": vetted_volume,
            "vetted_count": vetted_count,
            "volume_display": volume_display,
            "volume_display_subtitle": volume_display_subtitle,
            "high_win_rate": high_wr,
            "medium_win_rate": medium_wr,
            "low_win_rate": low_wr,
            "win_rate_distribution": dist,
        }

    def _get_system_health(self, accurate: bool = False):
        """Get system health status with real metrics (system-wide, matches Task Manager).
        accurate=True uses 1s CPU sampling for more accurate readings."""
        mem_mb = 0
        mem_pct = 0
        cpu_pct = 0
        uptime_hours = 0
        try:
            import psutil
            # System-wide CPU: longer interval = more accurate (blocks briefly)
            cpu_pct = psutil.cpu_percent(interval=1.0 if accurate else 0.1)
            # System memory: used % (matches Task Manager) and process RSS
            vmem = psutil.virtual_memory()
            mem_pct = vmem.percent
            proc = psutil.Process()
            mem_mb = proc.memory_info().rss / (1024 * 1024)
            create_time = proc.create_time()
            uptime_sec = time.time() - create_time
            uptime_hours = round(uptime_sec / 3600, 1)
        except ImportError:
            pass
        except Exception:
            pass

        # Discord/Telegram: "Connected" = webhook or bot configured (alerts can deliver)
        discord_ok = bool(
            self.config.get("discord_webhook_url")
            or self.config.get("discord_alerts_webhook_url")
            or self.config.get("discord_bot_token")
        )
        telegram_ok = bool(self.config.get("telegram_bot_token"))

        return {
            "status": "healthy",
            "api_connected": True,
            "database_connected": True,
            "telegram_connected": telegram_ok,
            "discord_connected": discord_ok,
            "polymarket_connected": True,
            "kalshi_connected": False,
            "jupiter_connected": False,
            "last_sync": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uptime_hours": uptime_hours,
            "memory_usage_mb": round(mem_mb, 1),
            "memory_usage_pct": round(mem_pct, 1),
            "cpu_usage_percent": round(cpu_pct, 1),
        }

    def _get_user_count(self):
        """Get user statistics."""
        return {
            "total_users": 1,
            "active_users": 1,
            "copy_traders": 0,
            "api_users": 0,
            "free_tier": 1,
            "premium_tier": 0,
        }

    def _get_settings(self):
        """Get current settings from in-memory config (reload at page/API entry points only)."""
        return {
            "vet_min_trades_won": self.config.get("vet_min_trades_won", 5),
            "vet_max_losses": self.config.get("vet_max_losses", 0),
            "vet_min_recent_wins": self.config.get("vet_min_recent_wins", 3),
            "collector_stats_skip_hours": int(self.config.get("collector_stats_skip_hours", 24) or 0),
            "classify_bulk_skip_hours": int(self.config.get("classify_bulk_skip_hours", 24) or 0),
            "vet_skip_hours": int(self.config.get("vet_skip_hours", 48) or 0),
            "vet_min_specialty_wins": self.config.get("vet_min_specialty_wins", 4),
            "win_rate_threshold": self.config.get("win_rate_threshold", 55.0),
            "smart_money_threshold": self.config.get("smart_money_threshold", 55.0),
            "whale_min_volume": self.config.get("whale_min_volume", 1000),
            "insider_min_size": self.config.get("insider_min_size", 10000),
            "alert_min_pnl": self.config.get("alert_min_pnl", 500),
            "alert_skip_low_confidence": self.config.get("alert_skip_low_confidence", True),
            "convergence_min_volume": self.config.get("convergence_min_volume", 5000),
            "copy_enabled": self.config.get("copy_enabled", False),
            "copy_multiplier": self.config.get("copy_multiplier", 1.0),
            "copy_removed": self.config.get("copy_removed", True),
            "telegram_enabled": self.config.get("telegram_enabled", False),
            "discord_enabled": self.config.get("discord_enabled", False),
            "alerts_enabled": self.config.get("alerts_enabled", True),
            "insider_alerts": self.config.get("insider_alerts", self.config.get("whale_alerts", True)),
            "convergence_alerts": self.config.get("convergence_alerts", True),
            "smart_money_alerts": self.config.get("smart_money_alerts", True),
            "contrarian_alerts": self.config.get("contrarian_alerts", False),
            "auto_vet_wallets": self.config.get("auto_vet_wallets", False),
            "monitor_interval": self.config.get("monitor_interval", 300),
            "scan_interval_sec": self.config.get("scan_interval_sec", 180),
            "cache_ttl_sec": self.config.get("cache_ttl_sec", 0),
            "wallet_stats_max_per_cycle": self.config.get("wallet_stats_max_per_cycle", 0),
            "wallet_discovery_enabled": self.config.get("wallet_discovery_enabled", True),
            "wallet_discovery_interval_sec": self.config.get("wallet_discovery_interval_sec", 1800),
            "wallet_discovery_max_new": self.config.get("wallet_discovery_max_new", 15),
            "wallet_discovery_max_wallets": self.config.get("wallet_discovery_max_wallets", 100),
            "wallet_discovery_gamma_supplement": self.config.get("wallet_discovery_gamma_supplement", True),
            "wallet_cleanup_enabled": self.config.get("wallet_cleanup_enabled", True),
            "wallet_cleanup_interval_sec": self.config.get("wallet_cleanup_interval_sec", 7200),
            "wallet_cleanup_min_win_rate": self.config.get("wallet_cleanup_min_win_rate", 40),
            "wallet_cleanup_min_trades": self.config.get("wallet_cleanup_min_trades", 5),
            "wallet_cleanup_grace_days": self.config.get("wallet_cleanup_grace_days", 7),
            "wallet_cleanup_remove_farmer": self.config.get("wallet_cleanup_remove_farmer", True),
            "wallet_cleanup_remove_bot": self.config.get("wallet_cleanup_remove_bot", True),
            "wallet_cleanup_bot_min_bot_score": self.config.get("wallet_cleanup_bot_min_bot_score", 90),
            "vet_max_bot_score": self.config.get("vet_max_bot_score", 70),
            "wallet_list_interval": self.config.get("wallet_list_interval", 604800),
            "dashboard_poll_interval_sec": int(self.config.get("dashboard_poll_interval_sec", 90) or 0),
        }

    def run(self, use_waitress: bool = None):
        """Run the dashboard. Starts background collector if api_factory was provided.

        Uses Waitress (production WSGI server) by default — no socket errors on Windows.
        Set DASHBOARD_DEBUG=1 or use_waitress=False for Flask dev server (hot reload).
        """
        if self.collector:
            self.collector.start()
            atexit.register(self._stop_collector)
            logger.info(
                "Background data collector started (scans every %ds)",
                self.collector.interval_sec,
            )
        else:
            # No background collector: run dashboard threads so stats/cleanup still run
            # even when wallet_discovery_enabled is False.
            storage_ref = self.storage
            config_ref = self.config

            if self.config.get("wallet_discovery_enabled", True):
                ref = [0.0]

                def _dashboard_wallet_discovery_loop():
                    from src.collector.runner import run_wallet_discovery_step

                    while True:
                        if hasattr(config_ref, "reload"):
                            try:
                                config_ref.reload()
                            except Exception:
                                pass
                        interval = int(config_ref.get("wallet_discovery_interval_sec", 1800) or 1800)
                        # Poll a few times per interval without hammering APIs (cap 2m, floor 15s).
                        sleep_sec = min(120, max(15, max(1, interval) // 12))
                        try:
                            af = APIClientFactory(config_ref)
                            run_wallet_discovery_step(
                                storage_ref, config_ref, af, ref
                            )
                        except Exception as e:
                            logger.warning("[Dashboard] wallet_discovery thread: %s", e)
                        time.sleep(sleep_sec)

                threading.Thread(
                    target=_dashboard_wallet_discovery_loop,
                    daemon=True,
                    name="dashboard-wallet-discovery",
                ).start()
                logger.info(
                    "Dashboard-only: auto wallet discovery thread running "
                    "(same rules as `main.py run`; interval %ss).",
                    int(self.config.get("wallet_discovery_interval_sec", 1800) or 1800),
                )

            # Dashboard-only: no collector = stats never refresh. Run a stats refresh thread
            # so 0/0/0 wallets get real data (and cleanup can remove trash correctly).
            def _dashboard_stats_refresh_loop():
                from src.wallet.calculator import WalletCalculator
                batch = 15
                sleep_interval = 1800  # 30 min
                last_run = [0.0]
                while True:
                    time.sleep(min(60, sleep_interval // 10))
                    if time.time() - last_run[0] < sleep_interval:
                        continue
                    try:
                        if hasattr(config_ref, "reload"):
                            try:
                                config_ref.reload()
                            except Exception:
                                pass
                        wlist = storage_ref.list_wallets()
                        if not wlist:
                            continue
                        # Prioritize wallets with 0 trades (stale or never refreshed)
                        zero_trade = [w for w in wlist if (w.total_trades or 0) == 0]
                        rest = [w for w in wlist if (w.total_trades or 0) > 0]
                        to_refresh = (zero_trade + rest)[:batch]
                        if not to_refresh:
                            continue
                        af = APIClientFactory(config_ref)
                        calc = WalletCalculator(af)
                        updated = 0
                        for w in to_refresh:
                            try:
                                tt, wins, wr, vol, _ = calc.calculate_wallet_stats(w.address)
                                storage_ref.update_wallet_stats(
                                    w.address, tt, wins, vol, win_rate=wr
                                )
                                updated += 1
                                time.sleep(0.25)
                            except Exception as e:
                                logger.debug("[Dashboard] stats refresh %s: %s", w.address[:12], e)
                        last_run[0] = time.time()
                        if updated:
                            logger.info(
                                "[Dashboard] Stats refresh: updated %d/%d wallet(s)",
                                updated,
                                len(to_refresh),
                            )
                    except Exception as e:
                        logger.warning("[Dashboard] stats_refresh thread: %s", e)

            threading.Thread(
                target=_dashboard_stats_refresh_loop,
                daemon=True,
                name="dashboard-stats-refresh",
            ).start()
            logger.info(
                "Dashboard-only: stats refresh thread running (batch %d every 30min).",
                15,
            )

            # Dashboard-only: run cleanup so trash wallets (0 trades, 0 wins, low win rate) get removed
            if self.config.get("wallet_cleanup_enabled", True):
                cleanup_ref = [0.0]

                def _dashboard_cleanup_loop():
                    from src.collector.runner import run_wallet_cleanup_step
                    while True:
                        if hasattr(config_ref, "reload"):
                            try:
                                config_ref.reload()
                            except Exception:
                                pass
                        interval = int(config_ref.get("wallet_cleanup_interval_sec", 3600) or 3600)
                        sleep_sec = min(600, max(60, interval // 6))
                        try:
                            run_wallet_cleanup_step(storage_ref, config_ref, cleanup_ref)
                        except Exception as e:
                            logger.warning("[Dashboard] cleanup thread: %s", e)
                        time.sleep(sleep_sec)

                threading.Thread(
                    target=_dashboard_cleanup_loop,
                    daemon=True,
                    name="dashboard-wallet-cleanup",
                ).start()
                logger.info(
                    "Dashboard-only: wallet cleanup thread running (every %ss).",
                    int(self.config.get("wallet_cleanup_interval_sec", 3600) or 3600),
                )

        use_production = use_waitress
        if use_production is None:
            use_production = os.getenv("DASHBOARD_DEBUG", "").lower() not in ("1", "true", "t", "yes")

        if use_production:
            try:
                from waitress import serve
                host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
                port = int(os.getenv("DASHBOARD_PORT", "5000"))
                logger.info("Starting Waitress server at http://%s:%d", host, port)
                serve(self.app, host=host, port=port, threads=4)
            except ImportError:
                logger.warning(
                    "Waitress not installed, falling back to Flask dev server (pip install waitress)"
                )
                self.app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
        else:
            self.app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)

    def _get_shared_market_cache(self) -> dict:
        """Return session-level market cache, pruning entries older than 2 hours."""
        import time as _time
        TTL = 7200  # 2 hours
        now = _time.time()
        with self._session_cache_lock:
            stale = [mid for mid, ts in self._session_cache_ts.items() if now - ts > TTL]
            for mid in stale:
                self._session_market_cache.pop(mid, None)
                self._session_cache_ts.pop(mid, None)
            return self._session_market_cache

    def _stop_collector(self):
        """Stop collector on shutdown (registered with atexit)."""
        if self.collector:
            self.collector.stop()

    def _register_collector_routes(self):
        """Register start/stop/status routes for the background collector."""

        @self.app.route("/api/collector/status", methods=["GET"])
        def collector_status():
            if self.collector and self.collector._thread and self.collector._thread.is_alive():
                return jsonify({"running": True, "interval_sec": self.collector.interval_sec})
            return jsonify({"running": False})

        @self.app.route("/api/collector/stop", methods=["POST"])
        def collector_stop():
            if not self.collector:
                return jsonify({"ok": False, "error": "No collector in this mode"}), 400
            self.collector.stop()
            logger.info("[Dashboard] Collector stopped via UI")
            return jsonify({"ok": True, "running": False})

        @self.app.route("/api/collector/start", methods=["POST"])
        def collector_start():
            if not self.collector:
                return jsonify({"ok": False, "error": "No collector in this mode"}), 400
            self.collector.start()
            logger.info("[Dashboard] Collector started via UI")
            return jsonify({"ok": True, "running": True})
