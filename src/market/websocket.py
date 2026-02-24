"""Real-time market data via WebSocket for Polymarket."""

import json
import threading
import time
from typing import Dict, List, Callable, Optional


class MarketWebSocket:
    """WebSocket client for real-time Polymarket data."""

    def __init__(self):
        self.ws = None
        self.running = False
        self.subscriptions = set()
        self.callbacks = []
        self._reconnect_delay = 5

    def subscribe(self, channel: str, callback: Callable):
        """Subscribe to a channel with callback."""
        self.subscriptions.add(channel)
        self.callbacks.append((channel, callback))

    def connect(self):
        """Connect to Polymarket WebSocket."""
        try:
            import websocket

            self.ws = websocket.WebSocketApp(
                "wss://gateway.polymarket.com/ws",
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open,
            )
            self.running = True
            thread = threading.Thread(target=self.ws.run_forever, daemon=True)
            thread.start()
        except ImportError:
            print(
                "[WS] websocket-client not installed. Run: pip install websocket-client"
            )
        except Exception as e:
            print(f"[WS] Connection error: {e}")

    def _on_message(self, ws, message):
        """Handle incoming message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "price_change":
                for channel, callback in self.callbacks:
                    try:
                        callback(data)
                    except:
                        pass
        except:
            pass

    def _on_error(self, ws, error):
        print(f"[WS] Error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[WS] Closed: {close_status_code}")
        self.running = False
        # Reconnect after delay
        if self._reconnect_delay < 60:
            self._reconnect_delay *= 2
            time.sleep(self._reconnect_delay)
            self.connect()

    def _on_open(self, ws):
        print("[WS] Connected")
        self._reconnect_delay = 5
        # Subscribe to channels
        for channel in self.subscriptions:
            ws.send(json.dumps({"type": "subscribe", "channel": channel}))

    def stop(self):
        """Stop the WebSocket."""
        self.running = False
        if self.ws:
            self.ws.close()


class CryptoPriceMonitor:
    """Monitor crypto prices via WebSocket for real-time alerts."""

    def __init__(self):
        self.ws = MarketWebSocket()
        self._last_prices = {}
        self._callbacks = []

    def start(self):
        """Start monitoring."""
        try:
            import websocket

            self.ws.connect()
        except ImportError:
            print("pip install websocket-client for real-time crypto alerts")

    def on_price_change(self, callback: Callable):
        """Register callback for price changes."""
        self._callbacks.append(callback)

    def stop(self):
        """Stop monitoring."""
        self.ws.stop()


# Singleton
crypto_ws = CryptoPriceMonitor()
