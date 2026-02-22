"""Arbitrage detection for Polymarket."""

from typing import List, Dict, Tuple, Optional
from src.market.api import APIClientFactory


class ArbitrageDetector:
    """Detect arbitrage opportunities in Polymarket markets."""

    # Minimum spread after fees (need profit margin)
    MIN_SPREAD = 0.99  # If YES + NO < 0.99, ~1%+ profit

    def __init__(self, api_factory: APIClientFactory, min_spread: float = MIN_SPREAD):
        """Initialize detector.

        Args:
            api_factory: The API client factory.
            min_spread: Minimum YES + NO to consider (default 0.98 for ~2% profit)
        """
        self.api = api_factory.get_polymarket_api()
        self.min_spread = min_spread

    def check_market_arb(
        self, market_id: str, min_volume: float = 1000
    ) -> Optional[Dict]:
        """Check a single market for arbitrage.

        Args:
            market_id: Market condition ID
            min_volume: Minimum volume to consider

        Returns:
            Dict with arbitrage info or None if no opportunity
        """
        market = self.api.get_market(market_id)
        if not market:
            return None

        # Check volume first - skip low volume markets
        volume = float(market.get("volume", 0) or 0)
        if volume < min_volume:
            return None

        # Get outcome prices
        outcome_prices = market.get("outcomePrices", "[]")
        if isinstance(outcome_prices, str):
            import json

            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError as e:
                print(f"Error decoding outcome_prices for market {market_id}: {e}")

        if not outcome_prices or len(outcome_prices) < 2:
            return None

        try:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        except (ValueError, IndexError):
            return None

        # Skip zero/null prices
        if yes_price <= 0 or no_price <= 0 or yes_price is None or no_price is None:
            return None

        # Skip markets where BOTH are effectively 0 (buggy data)
        if yes_price < 0.0001 and no_price < 0.0001:
            return None

        total = yes_price + no_price

        # Check for arbitrage opportunity
        if total < self.min_spread:
            spread = (1.0 - total) * 100  # Profit percentage
            return {
                "market_id": market_id,
                "question": market.get("question", "Unknown"),
                "yes_price": yes_price,
                "no_price": no_price,
                "total": total,
                "profit_pct": spread,
                "volume": volume,
                "condition_id": market.get("conditionId"),
            }

        return None

    def scan_markets(self, limit: int = 50, min_volume: float = 1000) -> List[Dict]:
        """Scan markets for arbitrage opportunities.

        Args:
            limit: Number of markets to check
            min_volume: Minimum volume to consider

        Returns:
            List of arbitrage opportunities
        """
        markets = self.api.get_active_markets(limit=limit)
        opportunities = []

        for market in markets:
            volume = float(market.get("volume", 0) or 0)
            if volume < min_volume:
                continue

            outcome_prices = market.get("outcomePrices", "[]")
            if isinstance(outcome_prices, str):
                import json

                try:
                    outcome_prices = json.loads(outcome_prices)
                except json.JSONDecodeError:
                    continue

            if not outcome_prices or len(outcome_prices) < 2:
                continue

            try:
                yes_price = float(outcome_prices[0])
                no_price = float(outcome_prices[1])
            except (ValueError, IndexError):
                continue

            # Skip zero/null prices
            if yes_price <= 0 or no_price <= 0:
                continue

            # Skip markets where BOTH are effectively 0 (buggy data)
            if yes_price < 0.0001 and no_price < 0.0001:
                continue

            total = yes_price + no_price

            if total < self.min_spread:
                spread = (1.0 - total) * 100
                opportunities.append(
                    {
                        "market_id": market.get("id") or market.get("conditionId"),
                        "question": market.get("question", "Unknown"),
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "total": total,
                        "profit_pct": spread,
                        "volume": volume,
                        "condition_id": market.get("conditionId"),
                    }
                )

        opportunities.sort(key=lambda x: x["profit_pct"], reverse=True)
        return opportunities

    def get_top_opportunities(self, limit: int = 5) -> List[Dict]:
        """Get top arbitrage opportunities.

        Args:
            limit: Number to return

        Returns:
            List of best opportunities
        """
        return self.scan_markets(limit=100, min_volume=500)[:limit]
