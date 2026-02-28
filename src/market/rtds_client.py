"""Polymarket RTDS WebSocket client for activity:trades.

Connects to wss://ws-live-data.polymarket.com, subscribes to activity:trades,
invokes callback on each trade. PING every 10s to keep connection alive.
"""

import json
import logging
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

RTDS_URL = "wss://ws-live-data.polymarket.com"
PING_INTERVAL = 10


class RTDSClient:
    """WebSocket client for Polymarket Real-Time Data Socket (activity:trades)."""

    def __init__(self, url: str = RTDS_URL, ping_interval: int = PING_INTERVAL):
        self.url = url
        self.ping_interval = ping_interval
        self._ws = None
        self._callback: Optional[Callable[[Dict], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def connect(self) -> None:
        """Connect to RTDS WebSocket."""
        try:
            import websocket
            self._ws = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
        except ImportError:
            raise ImportError("websocket-client required for RTDS. pip install websocket-client")

    def subscribe_trades(self, callback: Callable[[Dict], None]) -> None:
        """Subscribe to activity:trades and set callback for each trade."""
        self._callback = callback

    def start(self) -> None:
        """Start WebSocket in background thread."""
        if self._ws is None:
            self.connect()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="RTDSClient")
        self._thread.start()
        logger.info("[RTDS] Client started")

    def stop(self) -> None:
        """Stop WebSocket and thread."""
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[RTDS] Client stopped")

    def close(self) -> None:
        """Alias for stop."""
        self.stop()

    def _run(self) -> None:
        """Run WebSocket loop."""
        try:
            import websocket
            while not self._stop.is_set() and self._ws:
                self._ws.run_forever(ping_interval=self.ping_interval, ping_timeout=5)
                if self._stop.is_set():
                    break
                logger.warning("[RTDS] Connection closed, reconnecting in 5s...")
                time.sleep(5)
                self.connect()
                self._ws.run_forever(ping_interval=self.ping_interval, ping_timeout=5)
        except Exception as e:
            logger.exception("[RTDS] Run error: %s", e)

    def _on_open(self, ws) -> None:
        """Send subscribe message on connect."""
        sub = {
            "action": "subscribe",
            "subscriptions": [
                {"topic": "activity", "type": "trades"}
            ],
        }
        try:
            ws.send(json.dumps(sub))
            logger.info("[RTDS] Subscribed to activity:trades")
        except Exception as e:
            logger.warning("[RTDS] Subscribe failed: %s", e)

    def _on_message(self, ws, message: str) -> None:
        """Parse message and invoke callback for trade events."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        topic = data.get("topic", "")
        msg_type = data.get("type", "")
        payload = data.get("payload") or {}
        if topic == "activity" and msg_type == "trades":
            trade = self._parse_trade(payload)
            if trade and self._callback:
                try:
                    self._callback(trade)
                except Exception as e:
                    logger.warning("[RTDS] Callback error: %s", e)

    def _parse_trade(self, payload: dict) -> Optional[Dict]:
        """Extract trade fields for CopyEngine. Normalize to proxyWallet, market, asset_id, size, price, side."""
        if not payload:
            return None
        # Polymarket trade payload shape varies; extract common fields
        proxy_wallet = (
            payload.get("proxyWallet")
            or payload.get("proxy_wallet")
            or payload.get("maker")
            or payload.get("taker")
        )
        if not proxy_wallet:
            return None
        return {
            "proxyWallet": proxy_wallet,
            "market": payload.get("market") or payload.get("conditionId") or payload.get("market_id"),
            "asset_id": payload.get("asset_id") or payload.get("assetId") or payload.get("token_id"),
            "size": float(payload.get("size", 0) or payload.get("amount", 0) or 0),
            "price": float(payload.get("price", 0) or payload.get("outcomePrice", 0) or 0),
            "side": (payload.get("side") or payload.get("outcome") or "BUY").upper(),
            "raw": payload,
        }

    def _on_error(self, ws, error) -> None:
        logger.warning("[RTDS] WebSocket error: %s", error)

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        logger.info("[RTDS] WebSocket closed: %s %s", close_status_code, close_msg or "")
