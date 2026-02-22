"""Advanced convergence detection for PolySuite."""

from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime, timedelta, timezone
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.market.api import APIClientFactory


class ConvergenceDetector:
    """Detects when multiple high-performers are in the same market.

    Features:
    - Convergence: 2+ top wallets in same market
    - Early entry: Wallets entered within X minutes of market creation
    - Market age filtering: Only consider new markets
    - Time window: Only consider trades within recent window
    """

    def __init__(
        self,
        wallet_storage: WalletStorage = None,
        threshold: float = 55.0,
        min_trades: int = 10,
        api_factory: APIClientFactory = None,
        time_window_hours: int = 6,
        max_market_age_hours: int = 24,
        early_entry_minutes: int = 10,
    ):
        """Initialize detector.

        Args:
            wallet_storage: Storage for tracked wallets
            threshold: Win rate threshold for "high performer"
            min_trades: Minimum trades to qualify
            api_factory: The API client factory
            time_window_hours: Only consider wallet activity within this window
            max_market_age_hours: Only consider markets younger than this
            early_entry_minutes: Flag convergences where wallets entered within X mins
        """
        self.wallet_storage = wallet_storage or WalletStorage()
        self.threshold = threshold
        self.min_trades = min_trades
        self.api = api_factory.get_polymarket_api() if api_factory else None
        self.time_window_hours = time_window_hours
        self.max_market_age_hours = max_market_age_hours
        self.early_entry_minutes = early_entry_minutes

    def get_high_performers(self) -> List[Wallet]:
        """Get all tracked wallets above win rate threshold."""
        return self.wallet_storage.get_high_performers(self.threshold)

    def _get_market_age(self, market_id: str) -> Optional[float]:
        """Get market age in hours from creation time."""
        market = self.api.get_market(market_id)
        if not market:
            return None

        created_at = market.get("createdAt") or market.get("created_at")
        if not created_at:
            return None

        try:
            if isinstance(created_at, str):
                if created_at.endswith("Z"):
                    created_at = created_at[:-1] + "+00:00"
                created_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                created_time = datetime.fromtimestamp(
                    created_at / 1000, tz=timezone.utc
                )

            age = datetime.now(timezone.utc) - created_time
            return age.total_seconds() / 3600
        except:
            return None

    def _get_wallet_entry_time(self, wallet: str, market_id: str) -> Optional[datetime]:
        """Get when a wallet first traded in a market."""
        trades = self.api.get_wallet_trades(wallet, limit=100)

        for trade in trades:
            trade_market = trade.get("conditionId") or trade.get("market")
            if trade_market == market_id:
                ts = trade.get("timestamp")
                if ts:
                    try:
                        if ts.endswith("Z"):
                            ts = ts[:-1] + "+00:00"
                        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except:
                        pass

        try:
            positions = self.api.get_wallet_positions(wallet) if self.api else []
        except Exception:
            positions = []
        for pos in positions:
            pos_market = pos.get("conditionId") or pos.get("market")
            if pos_market == market_id:
                ts = pos.get("timestamp") or pos.get("createdAt")
                if ts:
                    try:
                        if isinstance(ts, (int, float)):
                            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                        if ts.endswith("Z"):
                            ts = ts[:-1] + "+00:00"
                        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except:
                        pass

        return None

    def _is_early_entry(self, wallet: str, market_id: str) -> bool:
        """Check if wallet entered within early_entry_minutes of market creation."""
        market = self.api.get_market(market_id)
        if not market:
            return False

        created_at = market.get("createdAt") or market.get("created_at")
        if not created_at:
            return False

        try:
            if isinstance(created_at, str):
                if created_at.endswith("Z"):
                    created_at = created_at[:-1] + "+00:00"
                market_created = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            else:
                market_created = datetime.fromtimestamp(
                    created_at / 1000, tz=timezone.utc
                )
        except:
            return False

        entry_time = self._get_wallet_entry_time(wallet, market_id)
        if not entry_time:
            return False

        minutes_after_creation = (entry_time - market_created).total_seconds() / 60
        return 0 <= minutes_after_creation <= self.early_entry_minutes

    def find_convergences(
        self,
        min_wallets: int = 2,
        only_early_entry: bool = False,
        only_new_markets: bool = True,
    ) -> List[Dict]:
        """Find markets where multiple high-performers are active.

        Args:
            min_wallets: Minimum wallets in same market
            only_early_entry: Only return convergences with early entry
            only_new_markets: Only consider markets younger than max_market_age_hours

        Returns:
            List of convergence dicts with market and wallet details
        """
        high_performers = self.get_high_performers()

        if not high_performers:
            return []

        now = datetime.now(timezone.utc)
        time_window = now - timedelta(hours=self.time_window_hours)

        market_convergences: Dict[str, Dict] = {}

        for wallet in high_performers:
            try:
                positions = (
                    self.api.get_wallet_positions(wallet.address) if self.api else []
                )
            except Exception:
                positions = []

            for pos in positions:
                market_id = pos.get("conditionId") or pos.get("market")
                if not market_id:
                    continue

                pos_ts = pos.get("timestamp")
                if pos_ts:
                    try:
                        if isinstance(pos_ts, (int, float)):
                            pos_time = datetime.fromtimestamp(
                                pos_ts / 1000, tz=timezone.utc
                            )
                        elif isinstance(pos_ts, str):
                            if pos_ts.endswith("Z"):
                                pos_ts = pos_ts[:-1] + "+00:00"
                            pos_time = datetime.fromisoformat(
                                pos_ts.replace("Z", "+00:00")
                            )
                        else:
                            continue

                        if pos_time < time_window:
                            continue
                    except:
                        pass

                if market_id not in market_convergences:
                    market_convergences[market_id] = {
                        "market_id": market_id,
                        "wallets": [],
                        "market_info": None,
                        "market_age_hours": None,
                        "has_early_entry": False,
                        "early_entry_wallets": [],
                    }

                wallet_ids = [
                    w["address"] for w in market_convergences[market_id]["wallets"]
                ]
                if wallet.address not in wallet_ids:
                    entry_info = {
                        "address": wallet.address,
                        "nickname": wallet.nickname,
                        "win_rate": wallet.win_rate,
                        "total_trades": wallet.total_trades,
                        "wins": wallet.wins,
                        "is_early_entry": False,
                    }

                    if self._is_early_entry(wallet.address, market_id):
                        entry_info["is_early_entry"] = True
                        market_convergences[market_id]["has_early_entry"] = True
                        market_convergences[market_id]["early_entry_wallets"].append(
                            wallet.nickname
                        )

                    market_convergences[market_id]["wallets"].append(entry_info)

        convergences = []
        for market_id, conv in market_convergences.items():
            if len(conv["wallets"]) < min_wallets:
                continue

            if only_early_entry and not conv["has_early_entry"]:
                continue

            market = self.api.get_market(market_id)
            conv["market_info"] = market
            conv["wallet_count"] = len(conv["wallets"])

            if only_new_markets:
                age = self._get_market_age(market_id)
                if age is None:
                    continue
                if age > self.max_market_age_hours:
                    continue
                conv["market_age_hours"] = age

            convergences.append(conv)

        convergences.sort(
            key=lambda x: (
                x["has_early_entry"],
                x["wallet_count"],
                -(x.get("market_age_hours") or 999),
            ),
            reverse=True,
        )

        return convergences

    def get_early_entry_convergences(self, min_wallets: int = 2) -> List[Dict]:
        """Get only convergences with early entry (wallets entered within first X minutes)."""
        return self.find_convergences(min_wallets=min_wallets, only_early_entry=True)

    def get_new_market_convergences(self, min_wallets: int = 2) -> List[Dict]:
        """Get convergences only on new markets."""
        return self.find_convergences(min_wallets=min_wallets, only_new_markets=True)

    def check_for_new_convergences(self, known_convergences: Set[str]) -> List[Dict]:
        """Check for new convergences not in known set."""
        all_convergences = self.find_convergences()
        return [c for c in all_convergences if c["market_id"] not in known_convergences]

    def get_convergence_summary(self) -> str:
        """Text summary of convergences with early entry info."""
        convergences = self.find_convergences()

        if not convergences:
            return "No convergences detected."

        lines = [f"Found {len(convergences)} convergence(s):\n"]

        for i, conv in enumerate(convergences[:5], 1):
            market = conv.get("market_info") or {}
            question = market.get("question", "Unknown")[:50]
            wallets = conv["wallets"]

            early_tag = " [EARLY ENTRY]" if conv.get("has_early_entry") else ""
            age_info = (
                f" ({conv.get('market_age_hours', 0):.1f}h old)"
                if conv.get("market_age_hours")
                else ""
            )

            lines.append(f"{i}. {question}{age_info}{early_tag}")
            lines.append(
                f"   {len(wallets)} traders: {', '.join(w['nickname'] for w in wallets)}"
            )

            if conv.get("early_entry_wallets"):
                lines.append(
                    f"   Early entrants: {', '.join(conv['early_entry_wallets'])}"
                )

        return "\n".join(lines)
