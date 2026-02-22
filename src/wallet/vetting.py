"""Advanced wallet vetting for PolySuite - filters bots and P&L cheaters."""

from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from src.market.api import APIClientFactory


class WalletVetting:
    """Vet wallets to filter out bots and P&L cheaters."""

    def __init__(self, api_factory: APIClientFactory):
        self.api = api_factory.get_polymarket_api()

    def vet_wallet(self, address: str, min_bet: float = 10) -> Optional[Dict]:
        """Fully vet a wallet and return analysis.

        Args:
            address: Wallet address
            min_bet: Minimum average bet size to qualify

        Returns:
            Dict with vetting results or None if failed
        """
        trades = self.api.get_wallet_trades(address, limit=500)
        if not trades:
            return None

        analysis = {
            "address": address,
            "total_trades": len(trades),
            "avg_bet_size": 0,
            "bot_score": 0,
            "unsettled_loses": 0,
            "resolved_markets_traded": 0,
            "win_rate_real": 0,
            "is_human": True,
            "is_settled": True,
            "passed": False,
            "issues": [],
        }

        total_volume = 0
        wins = 0
        unresolved_losses = 0
        resolved_markets = set()

        for trade in trades:
            size = float(trade.get("size", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            side = trade.get("side", "").upper()
            market_id = trade.get("conditionId") or trade.get("market")

            total_volume += size * price

            if market_id:
                market = self.api.get_market(market_id)
                if market:
                    resolved = market.get("resolved") or market.get("closed")
                    if resolved:
                        resolved_markets.add(market_id)

                        outcome = market.get("outcome")
                        if outcome:
                            if side == "BUY" and outcome.lower() == "yes":
                                wins += 1
                            elif side == "SELL" and outcome.lower() == "no":
                                wins += 1
                            else:
                                if not self._has_closed_position(address, market_id):
                                    unresolved_losses += 1

        analysis["total_volume"] = total_volume
        analysis["avg_bet_size"] = total_volume / len(trades) if trades else 0
        analysis["resolved_markets_traded"] = len(resolved_markets)

        if len(resolved_markets) > 0:
            analysis["win_rate_real"] = (wins / len(resolved_markets)) * 100

        analysis["unsettled_loses"] = unresolved_losses
        analysis["bot_score"] = self._calculate_bot_score(trades)

        if analysis["avg_bet_size"] < min_bet:
            analysis["issues"].append(
                f"Avg bet ${analysis['avg_bet_size']:.2f} below ${min_bet}"
            )

        if analysis["bot_score"] > 70:
            analysis["is_human"] = False
            analysis["issues"].append(
                f"Bot-like behavior (score: {analysis['bot_score']})"
            )

        if analysis["unsettled_loses"] > 3:
            analysis["is_settled"] = False
            analysis["issues"].append(f"{unresolved_losses} unresolved losses")

        if analysis["resolved_markets_traded"] < 5:
            analysis["issues"].append(f"Only {len(resolved_markets)} resolved markets")

        analysis["passed"] = (
            analysis["is_human"]
            and analysis["is_settled"]
            and analysis["avg_bet_size"] >= min_bet
            and len(resolved_markets) >= 5
        )

        return analysis

    def _calculate_bot_score(self, trades: List[Dict]) -> int:
        """Calculate how likely a wallet is a bot (0-100)."""
        if not trades:
            return 0

        bot_indicators = 0
        total = 0

        trade_times = []
        for i, trade in enumerate(trades):
            total += 1

            ts = trade.get("timestamp")
            if ts:
                try:
                    trade_times.append(datetime.fromisoformat(ts.replace("Z", "")))
                except Exception:
                    pass

            size = float(trade.get("size", 0) or 0)
            if size > 1000:
                bot_indicators += 1

            if i > 0 and len(trade_times) > 1:
                if (trade_times[-1] - trade_times[-2]).total_seconds() < 1:
                    bot_indicators += 2

        if len(trade_times) > 10:
            intervals = []
            for i in range(1, min(20, len(trade_times))):
                intervals.append((trade_times[i] - trade_times[i - 1]).total_seconds())

            avg_interval = sum(intervals) / len(intervals)
            if avg_interval < 5:
                bot_indicators += 5
            if avg_interval < 1:
                bot_indicators += 10

        return min(100, int((bot_indicators / max(total, 1)) * 100))

    def _has_closed_position(self, address: str, market_id: str) -> bool:
        """Check if wallet has closed their position in a market."""
        try:
            positions = self.api.get_wallet_positions(address) if self.api else []
        except Exception:
            positions = []
        for pos in positions:
            pos_market = pos.get("conditionId") or pos.get("market")
            if pos_market == market_id:
                return False
        return True

    def get_vetted_wallets(
        self, addresses: List[str], min_bet: float = 10, min_win_rate: float = 55
    ) -> List[Dict]:
        """Vet multiple wallets and return qualified ones.

        Args:
            addresses: List of wallet addresses
            min_bet: Minimum average bet size
            min_win_rate: Minimum win rate on resolved markets

        Returns:
            List of vetted wallets that pass criteria
        """
        qualified = []

        for addr in addresses:
            result = self.vet_wallet(addr, min_bet)
            if result and result["passed"]:
                if result["win_rate_real"] >= min_win_rate:
                    qualified.append(result)

        return qualified
