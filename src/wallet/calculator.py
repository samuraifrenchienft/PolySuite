"""Win rate calculator for tracked wallets."""

from typing import Dict, List, Tuple, Optional
from src.market.api import APIClientFactory

from datetime import datetime, timedelta

from src.wallet.resolution_stats import compute_polymarket_resolution_rollup


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
            ts = trade.get("timestamp")
            if not ts:
                continue
            try:
                trade_time = datetime.fromisoformat(str(ts).replace("Z", ""))
            except (ValueError, TypeError):
                continue
            if trade_time > datetime.now() - timedelta(days=days):
                recent_trades += 1

        return recent_trades

    def calculate_wallet_stats(
        self, address: str, max_markets: int = 120
    ) -> Tuple[int, int, float, int, int]:
        """Calculate trading statistics using **resolved** markets (same logic as vetting).

        Args:
            address: Wallet address
            max_markets: Cap unique conditionIds to fetch (rate limit / latency)

        Returns:
            Tuple of (total_trades, resolved_wins, win_rate_on_resolved, total_volume_usd,
            resolved_decisions). ``win_rate_on_resolved`` is 0 if no resolved decisions.
        """
        trades = self.api.get_wallet_trades(address, limit=500)

        if not trades:
            return 0, 0, 0.0, 0, 0

        rollup = compute_polymarket_resolution_rollup(
            self.api, address, trades, max_markets=max_markets
        )
        total_trades = rollup.total_trades
        wins = rollup.resolved_wins
        vol = int(round(rollup.total_volume))
        rd = rollup.resolved_decisions
        win_rate = (wins / rd * 100) if rd > 0 else 0.0

        return total_trades, wins, win_rate, vol, rd

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
            p = float(trade.get("price", 0) or 0)
            sz = float(trade.get("size", 0) or 0)
            usd = float(
                trade.get("usdcSize")
                or trade.get("usdAmount")
                or trade.get("usdc_amount")
                or 0
            )
            if usd <= 0 and sz and p:
                usd = abs(sz * p)
            markets[market_id]["total_volume"] += usd
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

        # Deduplicate market_ids to avoid N+1 API calls
        market_ids = set()
        trade_market_map = []
        for trade in trades:
            market_id = trade.get("conditionId") or trade.get("market")
            if market_id:
                market_ids.add(market_id)
                trade_market_map.append((trade, market_id))

        market_cache = {}
        for mid in market_ids:
            m = self.api.get_market_details(mid)
            if m:
                market_cache[mid] = m

        category_stats = {}
        for trade, market_id in trade_market_map:
            market = market_cache.get(market_id)
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
