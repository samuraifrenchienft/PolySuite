"""Signal generator - aggregates strategy signals for trading decisions.

Combines convergence, insider, contrarian, and wallet-based signals into
a unified view. Strategy logic remains in respective detectors.
"""

from typing import Any, Dict, List, Optional

from src.wallet import Wallet


class SignalGenerator:
    """Generate trading signals from multiple strategy sources."""

    def __init__(
        self,
        storage=None,
        api_factory=None,
        config=None,
    ):
        self.storage = storage
        self.api_factory = api_factory
        # Config: dict or Config instance with .get()
        self.config = config if config is not None else {}

    def generate_signals(
        self,
        wallets: Optional[List[Wallet]] = None,
        include_convergence: bool = True,
        include_insider: bool = True,
        include_contrarian: bool = True,
    ) -> List[Dict[str, Any]]:
        """Generate signals from all enabled strategy sources.

        Returns list of signal dicts with: type, action, wallet/market, confidence, data.
        """
        signals: List[Dict[str, Any]] = []

        if wallets is None and self.storage:
            wallets = self.storage.list_wallets()

        # 1. Convergence signals (2+ high-performers in same market)
        if include_convergence and self.api_factory and self.storage:
            try:
                from src.core.detector_factory import DetectorFactory

                factory = DetectorFactory(self.config, self.storage, self.api_factory)
                detector = factory.get_convergence_detector()
                convergences = detector.find_convergences(min_wallets=2)
                for c in convergences:
                    m = c.get("market_info") or {}
                    signals.append({
                        "type": "convergence",
                        "action": "follow",
                        "market_id": c.get("market_id"),
                        "question": (m.get("question") or "Unknown")[:120],
                        "wallet_count": c.get("wallet_count", 0),
                        "has_early_entry": c.get("has_early_entry", False),
                        "confidence": "high" if c.get("has_early_entry") and c.get("wallet_count", 0) >= 3 else "medium",
                        "data": c,
                    })
            except Exception:
                pass

        # 2. Insider signals (fresh wallet + large trade + winning outcome)
        if include_insider and self.api_factory:
            try:
                from src.core.detector_factory import DetectorFactory

                factory = DetectorFactory(self.config, self.storage, self.api_factory)
                detector = factory.get_insider_detector()
                raw = detector.scan_for_signals(limit=10)
                min_pnl = float(self.config.get("alert_min_pnl", 500) or 500)
                skip_low = self.config.get("alert_skip_low_confidence", True)
                for s in raw:
                    wt = s.get("winning_trade") or {}
                    if skip_low and (s.get("confidence") or "LOW").upper() == "LOW":
                        continue
                    if float(wt.get("pnl", 0) or 0) < min_pnl:
                        continue
                    signals.append({
                        "type": "insider",
                        "action": "follow",
                        "wallet": {"address": s.get("address"), "nickname": s.get("address", "")[:12] + "..."},
                        "confidence": (s.get("confidence") or "MEDIUM").lower(),
                        "trade_size": s.get("trade_size", 0),
                        "pnl": wt.get("pnl", 0),
                        "question": (wt.get("question") or "Unknown")[:80],
                        "data": s,
                    })
            except Exception:
                pass

        # 3. Contrarian signals (crowd imbalance + attractive payout)
        if include_contrarian and self.api_factory:
            try:
                from src.core.detector_factory import DetectorFactory

                factory = DetectorFactory(self.config, self.storage, self.api_factory)
                detector = factory.get_contrarian_detector()
                raw = detector.scan()
                for s in raw:
                    signals.append({
                        "type": "contrarian",
                        "action": "consider",
                        "market_id": s.get("market_id"),
                        "question": (s.get("question") or "Unknown")[:80],
                        "minority_side": s.get("minority_side"),
                        "payout": s.get("payout", 0),
                        "score": s.get("score", 0),
                        "confidence": "medium",
                        "data": s,
                    })
            except Exception:
                pass

        # 4. Wallet-based signals (high performers from tracked wallets)
        if wallets:
            threshold = float(self.config.get("win_rate_threshold", 55) or 55)
            min_trades = int(self.config.get("min_trades_for_high_performer", 10) or 10)
            for w in wallets:
                if (w.win_rate or 0) >= threshold and (w.total_trades or 0) >= min_trades:
                    if getattr(w, "is_bot", False) or getattr(w, "is_farmer", False):
                        continue
                    signals.append({
                        "type": "wallet",
                        "action": "track",
                        "wallet": {"address": w.address, "nickname": w.nickname},
                        "win_rate": w.win_rate,
                        "total_trades": w.total_trades,
                        "confidence": "high" if (w.win_rate or 0) >= 65 else "medium",
                        "data": w.to_dict() if hasattr(w, "to_dict") else {},
                    })

        return signals
