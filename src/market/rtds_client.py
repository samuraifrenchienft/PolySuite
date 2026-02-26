"""Minimal Polymarket RTDS WebSocket client for validation spike.

RTDS: wss://ws-live-data.polymarket.com
Docs: https://docs.polymarket.com/market-data/websocket/rtds
"""

import json
import threading
import time
from typing import Callable, Optional, List

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

RTDS_URL = "wss://ws-live-data.polymarket.com"
PING_INTERVAL = 5


class RTDSClient:
    """Minimal RTDS WebSocket client for feasibility validation."""

    def __init__(self, on_message: Optional[Callable] = None):
        self.on_message = on_message or (lambda m: None)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_message_ts: Optional[float] = None
        self._message_count = 0

    @property
    def last_message_latency_ms(self) -> Optional[float]:
        """Seconds since last message (for latency check)."""
        if self._last_message_ts is None:
            return None
        return (time.time() - self._last_message_ts) * 1000

    @property
    def message_count(self) -> int:
        return self._message_count

    def _run_sync(self):
        """Run WebSocket loop (blocking)."""
        if not HAS_WEBSOCKETS:
            print("[RTDS] websockets package not installed: pip install websockets")
            return

        import asyncio

        async def _connect():
            try:
                async with websockets.connect(RTDS_URL) as ws:
                    # Subscribe to activity (trade) topic - minimal subscription
                    sub = {"type": "subscribe", "topic": "activity"}
                    await ws.send(json.dumps(sub))
                    last_ping = time.time()
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=10)
                            self._message_count += 1
                            self._last_message_ts = time.time()
                            try:
                                data = json.loads(msg)
                                self.on_message(data)
                            except json.JSONDecodeError:
                                pass
                            # PING every 5s to keep alive
                            if time.time() - last_ping >= PING_INTERVAL:
                                await ws.send(json.dumps({"type": "ping"}))
                                last_ping = time.time()
                        except asyncio.TimeoutError:
                            continue
            except Exception as e:
                print(f"[RTDS] Connection error: {e}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_connect())

    def start(self):
        """Start WebSocket in background thread."""
        if not HAS_WEBSOCKETS:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run_sync, daemon=True, name="rtds-client")
        self._thread.start()
        return True

    def stop(self):
        """Stop WebSocket."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


def run_rtds_spike(duration_sec: float = 10) -> dict:
    """Run RTDS spike: connect, count messages, measure latency. Returns summary."""
    messages = []
    client = RTDSClient(on_message=messages.append)
    if not client.start():
        return {"ok": False, "error": "websockets not installed"}
    time.sleep(duration_sec)
    client.stop()
    return {
        "ok": True,
        "message_count": len(messages),
        "duration_sec": duration_sec,
        "messages_per_sec": round(len(messages) / duration_sec, 2) if duration_sec else 0,
    }
