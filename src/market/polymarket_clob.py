"""Polymarket CLOB API client using py-clob-client."""

import logging
from typing import Dict, List, Optional
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, PartialCreateOrderOptions

logger = logging.getLogger(__name__)


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

    def get_market(self, condition_id: str) -> Optional[Dict]:
        """Get market by condition_id (CLOB API supports this; Gamma does not)."""
        try:
            client = self._get_client()
            market = client.get_market(condition_id)
            if market is None:
                return None
            if hasattr(market, "__dict__"):
                return vars(market)
            if isinstance(market, dict):
                return market
            return None
        except Exception as e:
            logger.warning("CLOB get_market error: %s", e)
            return None

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
            logger.warning("Error fetching CLOB markets: %s", e)
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


class PolymarketCLOBTrading:
    """Authenticated CLOB client for order placement. Requires API creds from Polymarket Settings."""

    def __init__(
        self,
        host: str = "https://clob.polymarket.com",
        api_key: str = None,
        api_secret: str = None,
        api_passphrase: str = None,
    ):
        if not all([api_key, api_secret, api_passphrase]):
            raise ValueError("api_key, api_secret, and api_passphrase are required")
        creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
        self._client = ClobClient(host=host, creds=creds)

    def create_and_post_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str,
        neg_risk: bool = False,
        tick_size: str = "0.01",
    ) -> Optional[str]:
        """Create and post a GTC order. Returns order ID or None on failure."""
        try:
            from py_clob_client.order_builder.constants import BUY, SELL
            side_const = BUY if str(side).upper() == "BUY" else SELL
            args = OrderArgs(token_id=token_id, price=price, size=size, side=side_const)
            opts = PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)
            resp = self._client.create_and_post_order(args, options=opts)
            if isinstance(resp, dict):
                return resp.get("orderID") or resp.get("order_id")
            return str(resp) if resp is not None else None
        except Exception as e:
            logger.warning("CLOB create_and_post_order error: %s", e)
            return None
