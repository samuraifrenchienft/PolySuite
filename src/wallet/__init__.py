"""Wallet model for PolySuite.

Note: Tracked wallets are Polymarket wallets (Ethereum/Polygon addresses).
Solana is used as the base chain for the tracker (future rewards via Jupiter).
"""
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from typing import Optional
import json


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

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Wallet':
        """Create Wallet from dictionary."""
        allowed = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

    def is_high_performer(self, threshold: float = 55.0) -> bool:
        """Check if wallet is a high performer based on win rate threshold."""
        return self.win_rate >= threshold and self.total_trades >= 10

    def __str__(self) -> str:
        return f"{self.nickname} ({self.address[:8]}...): {self.win_rate:.1f}% win rate ({self.wins}/{self.total_trades})"
