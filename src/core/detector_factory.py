"""Centralized detector construction for PolySuite.

Single place to build convergence, insider, contrarian detectors with
consistent config. Reduces duplication across collector, dashboard, main.
"""

from typing import Any, Dict, Optional

from src.wallet.storage import WalletStorage
from src.market.api import APIClientFactory


class DetectorFactory:
    """Factory for strategy detectors with consistent config."""

    def __init__(
        self,
        config: Any,
        storage: Optional[WalletStorage] = None,
        api_factory: Optional[APIClientFactory] = None,
    ):
        self.config = config
        self.storage = storage
        self.api_factory = api_factory

    def _get(self, key: str, default: Any = None) -> Any:
        """Get config value (works with dict or Config instance)."""
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return self.config.get(key, default) if isinstance(self.config, dict) else default

    def get_convergence_detector(self):
        """Build ConvergenceDetector with config-driven params."""
        from src.alerts.convergence import ConvergenceDetector

        if not self.api_factory or not self.storage:
            raise ValueError("api_factory and storage required for ConvergenceDetector")

        return ConvergenceDetector(
            wallet_storage=self.storage,
            threshold=float(self._get("win_rate_threshold", 55) or 55),
            min_trades=int(self._get("min_trades_for_high_performer", 10) or 10),
            api_factory=self.api_factory,
            min_market_volume=float(self._get("convergence_min_volume", 5000) or 5000),
        )

    def get_insider_detector(self):
        """Build InsiderSignalDetector with config-driven params."""
        from src.alerts.insider_signal import InsiderSignalDetector

        if not self.api_factory:
            raise ValueError("api_factory required for InsiderSignalDetector")

        polymarket = self.api_factory.get_polymarket_api()
        min_size = float(self._get("insider_min_size", 10000) or 10000)

        return InsiderSignalDetector(
            polymarket_api=polymarket,
            insider_detector=True,
            api_factory=self.api_factory,
            min_trade_usd=min_size,
            fresh_max_trades=10,
        )

    def get_contrarian_detector(self):
        """Build ContrarianDetector with config-driven params."""
        from src.alerts.contrarian import ContrarianDetector

        if not self.api_factory:
            raise ValueError("api_factory required for ContrarianDetector")

        polymarket = self.api_factory.get_polymarket_api()
        return ContrarianDetector(
            polymarket_api=polymarket,
            min_volume=float(self._get("contrarian_min_volume", 10000) or 10000),
            min_imbalance=float(self._get("contrarian_min_imbalance", 0.6) or 0.6),
            payout_range=(0.20, 0.40),
            limit=10,
        )
