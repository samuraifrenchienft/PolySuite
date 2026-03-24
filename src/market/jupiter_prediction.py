"""Jupiter Prediction Market API client for PolySuite."""

import logging
import requests
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from src.config import Config

logger = logging.getLogger(__name__)

JUPITER_PREDICTION_API = "https://api.jup.ag/prediction/v1"


class JupiterPredictionAPI:
    """Client for Jupiter Prediction Market API."""

    def __init__(self, api_key: str = None):
        """Initialize API client."""
        self.session = requests.Session()
        config = Config()
        self.api_key = api_key or config.jupiter_id
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key

    def close(self):
        """Close the session."""
        self.session.close()

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make GET request to Jupiter API."""
        url = f"{JUPITER_PREDICTION_API}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Error fetching %s: %s", url, e)
            return None

    def get_events(
        self,
        provider: str = "polymarket",
        category: str = None,
        filter: str = None,
        sort_by: str = "volume",
        limit: int = 50,
        include_markets: bool = True,
    ) -> List[Dict]:
        """Get prediction events."""
        params = {
            "provider": provider,
            "includeMarkets": include_markets,
            "sortBy": sort_by,
            "sortDirection": "desc",
        }
        if category:
            params["category"] = category
        if filter:
            params["filter"] = filter

        result = self._get("/events", params)
        if result and "data" in result:
            return result["data"][:limit]
        return []

    def get_event(self, event_id: str, provider: str = "polymarket") -> Optional[Dict]:
        """Get single event details."""
        return self._get(f"/events/{event_id}", {"provider": provider})

    def get_event_markets(
        self, event_id: str, provider: str = "polymarket"
    ) -> List[Dict]:
        """Get markets for an event."""
        result = self._get(f"/events/{event_id}/markets", {"provider": provider})
        if result and "data" in result:
            return result["data"]
        return []

    def get_market(
        self, market_id: str, provider: str = "polymarket"
    ) -> Optional[Dict]:
        """Get market details."""
        return self._get(f"/markets/{market_id}", {"provider": provider})

    def get_positions(
        self,
        owner: str = None,
        market: str = None,
        provider: str = "polymarket",
    ) -> List[Dict]:
        """Get positions (for a wallet or market)."""
        params = {"provider": provider}
        if owner:
            params["owner"] = owner
        if market:
            params["market"] = market

        result = self._get("/positions", params)
        if result and "data" in result:
            return result["data"]
        return []

    def get_wallet_positions(
        self, address: str, provider: str = "polymarket"
    ) -> List[Dict]:
        """Get all positions for a wallet."""
        return self.get_positions(owner=address, provider=provider)

    def get_trades(
        self,
        market: str = None,
        owner: str = None,
        provider: str = "polymarket",
        limit: int = 100,
    ) -> List[Dict]:
        """Get recent trades."""
        params = {"provider": provider, "limit": limit}
        if market:
            params["market"] = market
        if owner:
            params["owner"] = owner

        result = self._get("/trades", params)
        if result and "data" in result:
            return result["data"]
        return []

    def get_wallet_trades(
        self, address: str, provider: str = "polymarket", limit: int = 100
    ) -> List[Dict]:
        """Get trade history for a wallet."""
        return self.get_trades(owner=address, provider=provider, limit=limit)

    def get_orderbook(
        self, market_id: str, provider: str = "polymarket"
    ) -> Optional[Dict]:
        """Get orderbook for a market."""
        return self._get(f"/orderbook/{market_id}", {"provider": provider})

    def get_leaderboards(
        self,
        metric: str = "pnl",
        provider: str = "polymarket",
        limit: int = 50,
    ) -> List[Dict]:
        """Get leaderboard rankings."""
        result = self._get(
            "/leaderboards", {"metric": metric, "provider": provider, "limit": limit}
        )
        if result and "data" in result:
            return result["data"]
        return []

    def get_history(
        self,
        owner: str,
        provider: str = "polymarket",
        limit: int = 100,
    ) -> List[Dict]:
        """Get trading history for a wallet."""
        result = self._get(
            "/history", {"owner": owner, "provider": provider, "limit": limit}
        )
        if result and "data" in result:
            return result["data"]
        return []

    def get_trading_status(self, provider: str = "polymarket") -> Optional[Dict]:
        """Get trading status."""
        return self._get("/trading-status", {"provider": provider})

    def get_active_markets(
        self,
        provider: str = "polymarket",
        limit: int = 50,
    ) -> List[Dict]:
        """Get active (open) markets."""
        events = self.get_events(provider=provider, include_markets=True, limit=limit)
        markets = []

        for event in events:
            if not event.get("isActive"):
                continue

            event_markets = event.get("markets", [])
            for market in event_markets:
                if market.get("status") == "open":
                    market["event_id"] = event.get("eventId")
                    market["event_title"] = event.get("metadata", {}).get("title", "")
                    market["category"] = event.get("category", "")
                    market["provider"] = provider
                    markets.append(market)

        return markets

    def get_new_events(
        self,
        provider: str = "polymarket",
        hours: int = 24,
        limit: int = 20,
    ) -> List[Dict]:
        """Get newly created events."""
        return self.get_events(provider=provider, filter="new", limit=limit)

    def get_trending_events(
        self,
        provider: str = "polymarket",
        limit: int = 20,
    ) -> List[Dict]:
        """Get trending events."""
        return self.get_events(provider=provider, filter="trending", limit=limit)

    def get_categories(self, provider: str = "polymarket") -> List[str]:
        """Get available categories."""
        return [
            "crypto",
            "sports",
            "politics",
            "esports",
            "culture",
            "economics",
            "tech",
        ]
