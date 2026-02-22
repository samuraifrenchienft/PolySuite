"""Calculates a wallet's portfolio."""

from typing import List
from src.wallet.portfolio import Portfolio, Position
from src.market.api import APIClientFactory


class PortfolioCalculator:
    """Calculates a wallet's portfolio."""

    def __init__(self, api_factory: APIClientFactory):
        """Initialize the calculator."""
        self.api = api_factory.get_polymarket_api()

    def calculate_portfolio(self, address: str, nickname: str) -> Portfolio:
        """Calculate a wallet's portfolio."""
        positions = self._get_positions(address)
        total_value = sum(p.value for p in positions)

        return Portfolio(
            address=address,
            nickname=nickname,
            total_value=total_value,
            positions=positions,
        )

    def _get_positions(self, address: str) -> List[Position]:
        """Get a wallet's positions from the API."""
        try:
            raw_positions = self.api.get_wallet_positions(address) if self.api else []
        except Exception:
            raw_positions = []
        positions = []

        for pos in raw_positions:
            market_id = pos.get("market_id")
            if not market_id:
                continue

            market = self.api.get_market(market_id)
            if not market:
                continue

            outcome = pos.get("outcome")
            shares = float(pos.get("shares", 0))
            entry_price = float(pos.get("entry_price", 0))
            current_price = self.api.get_token_price(pos.get("token_id")) or 0.0
            value = shares * current_price

            positions.append(
                Position(
                    market=market.get("question", "Unknown"),
                    outcome=outcome,
                    shares=shares,
                    entry_price=entry_price,
                    current_price=current_price,
                    value=value,
                )
            )

        return positions
