"""Polymarket CLOB API client using py-clob-client."""

from typing import Dict, List, Optional
from py_clob_client.client import ClobClient


class PolymarketCLOB:
    """Client for Polymarket CLOB API using py-clob-client.

    Provides more reliable market data and pricing.
    """

    def __init__(self, host: str = "https://clob.polymarket.com"):
        """Initialize CLOB client."""
        self.host = host
        self._client = None

    def _get_client(self) -> ClobClient:
        """Get or create CLOB client."""
        if self._client is None:
            self._client = ClobClient(host=self.host)
        return self._client

    def close(self):
        """Close the client."""
        self._client = None

    def get_markets(self, limit: int = 100) -> List[Dict]:
        """Get markets from CLOB."""
        try:
            client = self._get_client()
            markets = client.get_markets()
            # CLOB returns dict with pagination, extract markets
            if isinstance(markets, dict):
                markets = markets.get("data", []) or []
            # Convert to dict format similar to our existing API
            result = []
            for m in markets[:limit]:
                if hasattr(m, "__dict__"):
                    result.append(vars(m))
                else:
                    result.append(m)
            return result
        except Exception as e:
            print(f"Error fetching CLOB markets: {e}")
            return []

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        try:
            client = self._get_client()
            return client.get_midpoint(token_id)
        except Exception as e:
            return None

    def get_last_trade_price(self, token_id: str) -> Optional[float]:
        """Get last trade price for a token."""
        try:
            client = self._get_client()
            return client.get_last_trade_price(token_id)
        except Exception as e:
            return None

    def get_markets_midpoints(self, token_ids: List[str]) -> Dict[str, float]:
        """Get midpoints for multiple tokens."""
        try:
            client = self._get_client()
            return client.get_midpoints(token_ids)
        except Exception as e:
            return {}

    def get_order_book(self, token_id: str) -> Optional[Dict]:
        """Get order book for a token."""
        try:
            client = self._get_client()
            return client.get_order_book(token_id)
        except Exception as e:
            return None

    def get_spread(self, token_id: str) -> Optional[float]:
        """Get spread for a token."""
        try:
            client = self._get_client()
            return client.get_spread(token_id)
        except Exception as e:
            return None

    def get_fee_rate(self) -> Optional[float]:
        """Get current fee rate."""
        try:
            client = self._get_client()
            return client.get_fee_rate_bps()
        except Exception as e:
            return None

    def health_check(self) -> bool:
        """Check if API is healthy."""
        try:
            client = self._get_client()
            return client.get_ok() is not None
        except Exception:
            return False
