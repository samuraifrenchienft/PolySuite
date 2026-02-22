"""Portfolio tracking for PolySuite."""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Position:
    """Represents a single position in a market."""
    market: str
    outcome: str
    shares: float
    entry_price: float
    current_price: float
    value: float


@dataclass
class Portfolio:
    """Represents a wallet's portfolio."""
    address: str
    nickname: str
    total_value: float
    positions: List[Position] = field(default_factory=list)
