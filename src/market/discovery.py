"""Market discovery module for detecting new markets."""

import time
from typing import List, Dict, Set, Optional, Callable
from src.market.api import APIClientFactory


class MarketDiscovery:
    """Discovers new markets on Polymarket."""

    def __init__(
        self,
        api_factory: APIClientFactory,
        tracked_categories: Optional[List[str]] = None,
    ):
        """Initialize market discovery."""
        self.api = api_factory.get_polymarket_api()
        self.known_markets: Set[str] = set()
        self.tracked_categories = tracked_categories or []
        self._initialize_known_markets()

    def _initialize_known_markets(self):
        """Load known markets on startup."""
        markets = self.api.get_active_markets(limit=200) or []
        if self.tracked_categories:
            markets = [
                m for m in markets if m.get("category") in self.tracked_categories
            ]
        self.known_markets = {
            m["id"]: m.get("category") for m in markets if m.get("id")
        }

    def check_for_new_markets(self) -> List[Dict]:
        """Check for new markets since last check.

        Returns:
            List of new market dictionaries
        """
        current_markets = self.api.get_active_markets(limit=200) or []
        if self.tracked_categories:
            current_markets = [
                m
                for m in current_markets
                if m.get("category") in self.tracked_categories
            ]
        current_ids = {
            m["id"]: m.get("category") for m in current_markets if m.get("id")
        }

        new_ids = {k: v for k, v in current_ids.items() if k not in self.known_markets}

        if new_ids:
            new_markets = [m for m in current_markets if m.get("id") in new_ids]
            for market in new_markets:
                market["category"] = new_ids.get(market["id"])
            self.known_markets.update(new_ids)
            return new_markets

        return []

    def get_new_markets_stream(
        self, interval: int = 60, callback: Optional[Callable] = None
    ):
        """Continuously check for new markets.

        Args:
            interval: Seconds between checks
            callback: Optional callback function for each new market

        Yields:
            New market dictionaries
        """
        while True:
            try:
                new_markets = self.check_for_new_markets()

                for market in new_markets:
                    print(f"🆕 New market: {market.get('question', 'Unknown')[:60]}")
                    if callback:
                        callback(market)
                    yield market

                time.sleep(interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error in market discovery: {e}")
                time.sleep(5)

    def get_markets_by_category(self, category: str) -> List[Dict]:
        """Get markets filtered by category/group."""
        events = self.api.get_events(limit=100)
        markets = []

        for event in events:
            group_title = event.get("groupItemTitle", "")
            if category.lower() in group_title.lower():
                event_markets = self.api.get_event_markets(event.get("id", ""))
                markets.extend(event_markets)

        return markets

    def search_markets(self, query: str) -> List[Dict]:
        """Search markets by question text."""
        markets = self.api.get_active_markets(limit=100) or []
        if self.tracked_categories:
            markets = [
                m for m in markets if m.get("category") in self.tracked_categories
            ]
        query_lower = query.lower()

        return [m for m in markets if query_lower in m.get("question", "").lower()]

    def get_market_wallets(self, market_id: str, min_volume: float = 100) -> List[Dict]:
        """Get wallets that traded in a market with volume info.

        Args:
            market_id: The market ID
            min_volume: Minimum trade volume to include

        Returns:
            List of dicts with wallet address and total volume
        """
        trades = self.api.get_market_trades(market_id, limit=500)

        wallet_volumes = {}
        for trade in trades:
            addr = trade.get("address") or trade.get("user")
            if not addr:
                continue

            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            volume = size * price

            if addr not in wallet_volumes:
                wallet_volumes[addr] = 0
            wallet_volumes[addr] += volume

        return [
            {"address": addr, "volume": vol}
            for addr, vol in wallet_volumes.items()
            if vol >= min_volume
        ]

    def get_crypto_timeframe_markets(
        self, timeframe: str = "15min", limit: int = 50
    ) -> List[Dict]:
        """Get crypto time-frame markets (e.g., BTC 15min, 5min up/down).

        Args:
            timeframe: Time frame to search for ("5min", "15min", "1hour")
            limit: Number of markets to fetch

        Returns:
            List of matching markets
        """
        all_markets = self.api.get_active_markets(limit=limit * 2) or []
        timeframe_lower = timeframe.lower().replace(" ", "")

        crypto_keywords = ["btc", "eth", "bitcoin", "ethereum"]

        matches = []
        for m in all_markets:
            question = m.get("question", "").lower()
            group = m.get("groupItemTitle", "").lower()

            is_crypto = any(kw in question or kw in group for kw in crypto_keywords)
            is_timeframe = timeframe_lower in question.replace(" ", "")

            if is_crypto and is_timeframe:
                matches.append(m)

        return matches[:limit]
