"""Win rate calculator for tracked wallets."""

from typing import Dict, List, Tuple, Optional
from src.market.api import APIClientFactory


from datetime import datetime, timedelta


class WalletCalculator:
    """Calculates win rates and trading stats for wallets."""

    def __init__(self, api_factory: APIClientFactory):
        """Initialize calculator with API client factory."""
        self.api = api_factory.get_polymarket_api()

    def count_recent_trades(self, address: str, days: int) -> int:
        """Count the number of trades for a wallet in the last N days."""
        trades = self.api.get_wallet_trades(address, limit=500)
        if not trades:
            return 0

        recent_trades = 0
        for trade in trades:
            trade_time = datetime.fromisoformat(trade["timestamp"].replace("Z", ""))
            if trade_time > datetime.now() - timedelta(days=days):
                recent_trades += 1

        return recent_trades

    def calculate_wallet_stats(self, address: str) -> Tuple[int, int, float, int]:
        """Calculate trading statistics for a wallet.

        Args:
            address: Wallet address

        Returns:
            Tuple of (total_trades, wins, win_rate, total_volume)
        """
        trades = self.api.get_wallet_trades(address, limit=500)

        if not trades:
            return 0, 0, 0.0, 0

        total_trades = len(trades)
        wins = 0
        total_volume = 0

        # Calculate win rate based on trade profitability heuristic
        # A trade is "potentially winning" if they bought at favorable prices
        # This is approximate - actual wins require market resolution data
        for trade in trades:
            side = trade.get("side", "").upper()
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            total_volume += size

            # Buy Yes at < 0.5 = potentially winning (bought cheap)
            if side == "BUY" and price < 0.5:
                wins += 1
            # Sell Yes at > 0.5 = potentially winning (sold expensive)
            elif side == "SELL" and price > 0.5:
                wins += 1

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        return total_trades, wins, win_rate, total_volume

    def get_wallet_markets(self, address: str) -> List[Dict]:
        """Get all markets a wallet has traded in.

        Args:
            address: Wallet address

        Returns:
            List of market IDs with trade details
        """
        trades = self.api.get_wallet_trades(address, limit=500)

        markets = {}
        for trade in trades:
            market_id = trade.get("conditionId") or trade.get("market")
            if not market_id:
                continue

            if market_id not in markets:
                markets[market_id] = {
                    "market_id": market_id,
                    "trades": [],
                    "total_volume": 0,
                    "side": None,
                }

            markets[market_id]["trades"].append(trade)
            markets[market_id]["total_volume"] += float(trade.get("size", 0))
            markets[market_id]["side"] = trade.get("side")

        return list(markets.values())

    def get_active_positions(self, address: str) -> List[Dict]:
        """Get current active positions for a wallet.

        Args:
            address: Wallet address

        Returns:
            List of active positions
        """
        try:
            return self.api.get_wallet_positions(address) if self.api else []
        except Exception:
            return []

    def calculate_win_rate_by_category(
        self, address: str
    ) -> Dict[str, Dict[str, float]]:
        """Calculate win rates by market category."""
        trades = self.api.get_wallet_trades(address, limit=500)
        if not trades:
            return {}

        category_stats = {}
        for trade in trades:
            market_id = trade.get("conditionId") or trade.get("market")
            if not market_id:
                continue

            market = self.api.get_market_details(market_id)
            if not market:
                continue

            category = market.get("category", "Unknown")
            if category not in category_stats:
                category_stats[category] = {"total_trades": 0, "wins": 0}

            category_stats[category]["total_trades"] += 1
            side = trade.get("side", "").upper()
            price = float(trade.get("price", 0))

            if side == "BUY" and price < 0.5:
                category_stats[category]["wins"] += 1
            elif side == "SELL" and price > 0.5:
                category_stats[category]["wins"] += 1

        win_rates = {}
        for category, stats in category_stats.items():
            win_rate = (
                (stats["wins"] / stats["total_trades"] * 100)
                if stats["total_trades"] > 0
                else 0.0
            )
            win_rates[category] = {
                "win_rate": win_rate,
                "total_trades": stats["total_trades"],
            }

        return win_rates
