"""Wallet model for PolySuite.

Note: Tracked wallets are Polymarket wallets (Ethereum/Polygon addresses).
Solana is used as the base chain for the tracker (future rewards via Jupiter).
"""

from dataclasses import dataclass, asdict, fields
from datetime import datetime
from typing import Optional, List
import json


class WalletTier:
    """Wallet tier constants."""

    WATCH = "watch"
    VETTED = "vetted"
    ELITE = "elite"


@dataclass
class Wallet:
    """Represents a tracked wallet with trading stats."""

    address: str
    nickname: str
    total_trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    last_updated: Optional[str] = None
    created_at: Optional[str] = None
    is_smart_money: bool = False
    trade_volume: int = 0
    bot_score: Optional[int] = None
    unresolved_exposure_usd: Optional[float] = None
    last_vetted_at: Optional[str] = None
    total_pnl: Optional[float] = None
    roi_pct: Optional[float] = None
    conviction_score: Optional[float] = None
    is_specialty: bool = False
    specialty_note: Optional[str] = None
    specialty_market_id: Optional[str] = None
    specialty_category: Optional[str] = None
    is_win_streak_badge: bool = False
    specialty_roi_pct: Optional[float] = None
    is_pinned: bool = False

    # WalletClassifier fields
    classification: Optional[str] = None
    classification_reason: Optional[str] = None
    total_score: float = 0.0
    is_bot: bool = False
    is_farmer: bool = False
    is_high_loss_rate: bool = False
    current_win_streak: int = 0
    max_win_streak: int = 0
    stats_7d_volume: float = 0.0
    stats_7d_win_rate: float = 0.0
    stats_14d_volume: float = 0.0
    stats_14d_win_rate: float = 0.0

    # ============ NEW TIER SYSTEM FIELDS ============
    # Tier management
    tier: str = "watch"  # watch, vetted, elite
    tier_changed_at: Optional[str] = None
    tier_change_reason: Optional[str] = None

    # Scoring
    score_7d: float = 0.0
    score_14d: float = 0.0
    score_30d: float = 0.0
    last_scored_at: Optional[str] = None

    # Streaks and activity
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    last_trade_at: Optional[str] = None
    days_inactive: int = 0

    # Category specialization
    specialty_category_2: Optional[str] = None
    specialty_win_rate: float = 0.0
    specialty_volume: float = 0.0

    # Betting patterns
    avg_hold_duration_hours: float = 0.0
    preferred_odds_range: str = "medium"  # low, medium, high, very_high
    size_consistency: float = 0.0  # 0=variable, 1=consistent

    # Volume-weighted metrics
    volume_weighted_win_rate: float = 0.0
    recent_7d_volume: float = 0.0
    recent_14d_volume: float = 0.0
    recent_7d_trades: int = 0
    recent_14d_trades: int = 0
    recent_7d_win_rate: float = 0.0
    recent_14d_win_rate: float = 0.0
    recent_7d_pnl: float = 0.0
    recent_14d_pnl: float = 0.0

    # Pattern tracking (stored as JSON strings)
    trading_hours: str = "{}"  # {"0-6": 10, "6-12": 25, ...}
    trading_days: str = "{}"  # {"mon": 15, "tue": 20, ...}
    odds_distribution: str = "{}"  # {"low": 20, "medium": 40, ...}

    # Category breakdown
    category_stats: str = (
        "{}"  # JSON: {"politics": {"trades": 50, "wins": 30, "volume": 10000}, ...}
    )

    def __post_init__(self):
        """Set timestamps on creation."""
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.last_updated:
            self.last_updated = datetime.utcnow().isoformat()

    def update_stats(self, total_trades: int, wins: int) -> None:
        """Update trading statistics and recalculate win rate."""
        self.total_trades = total_trades
        self.wins = wins
        self.win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        self.last_updated = datetime.utcnow().isoformat()

    def get_trading_hours_dict(self) -> dict:
        """Get trading hours as dict."""
        try:
            return json.loads(self.trading_hours) if self.trading_hours else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_trading_days_dict(self) -> dict:
        """Get trading days as dict."""
        try:
            return json.loads(self.trading_days) if self.trading_days else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_odds_distribution_dict(self) -> dict:
        """Get odds distribution as dict."""
        try:
            return json.loads(self.odds_distribution) if self.odds_distribution else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_category_stats(self) -> dict:
        """Get category stats as dict."""
        try:
            return json.loads(self.category_stats) if self.category_stats else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_trading_hours_dict(self, data: dict) -> None:
        """Set trading hours from dict."""
        self.trading_hours = json.dumps(data)

    def set_trading_days_dict(self, data: dict) -> None:
        """Set trading days from dict."""
        self.trading_days = json.dumps(data)

    def set_odds_distribution_dict(self, data: dict) -> None:
        """Set odds distribution from dict."""
        self.odds_distribution = json.dumps(data)

    def set_category_stats(self, data: dict) -> None:
        """Set category stats from dict."""
        self.category_stats = json.dumps(data)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Wallet":
        """Create Wallet from dictionary."""
        allowed = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

    def is_high_performer(self, threshold: float = 55.0) -> bool:
        """Check if wallet is a high performer based on win rate threshold."""
        return self.win_rate >= threshold and self.total_trades >= 10

    def is_elite(self) -> bool:
        """Check if wallet is in Elite tier."""
        return self.tier == WalletTier.ELITE

    def is_vetted(self) -> bool:
        """Check if wallet is in Vetted tier."""
        return self.tier == WalletTier.VETTED

    def is_watch(self) -> bool:
        """Check if wallet is in Watch tier."""
        return self.tier == WalletTier.WATCH

    def should_demote_to_watch(self) -> bool:
        """Check if wallet should be demoted from Vetted to Watch."""
        if self.tier != WalletTier.VETTED:
            return False

        # Score threshold
        if self.total_score < 40:
            return True

        # Consecutive losses
        if self.consecutive_losses >= 5:
            return True

        # Inactive
        if self.days_inactive > 14:
            return True

        # Flagged as bot/farmer
        if self.is_bot or self.is_farmer:
            return True

        return False

    def should_promote_to_vetted(self) -> bool:
        """Check if wallet should be promoted from Watch to Vetted."""
        if self.tier != WalletTier.WATCH:
            return False

        # Must pass all checks
        if self.total_score < 50:
            return False
        if self.win_rate < 50:
            return False
        if self.is_bot or self.is_farmer or self.is_high_loss_rate:
            return False

        return True

    def should_promote_to_elite(self) -> bool:
        """Check if wallet should be promoted from Vetted to Elite."""
        if self.tier != WalletTier.VETTED:
            return False

        # Stricter requirements
        if self.total_score < 80:
            return False
        if self.win_rate < 60:
            return False
        if self.current_win_streak < 5:
            return False

        return True

    def get_risk_level(self) -> str:
        """Get risk level based on patterns."""
        if self.size_consistency > 0.8:
            return "conservative"
        elif self.size_consistency > 0.4:
            return "moderate"
        else:
            return "aggressive"

    def __str__(self) -> str:
        return f"{self.nickname} ({self.address[:8]}...): {self.win_rate:.1f}% win rate ({self.wins}/{self.total_trades}) [{self.tier.upper()}]"
