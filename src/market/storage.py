"""Market data storage for PolySuite."""

import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from src.config.paths import DB_PATH

logger = logging.getLogger(__name__)


class MarketStorage:
    """Manages SQLite database for market data."""

    def __init__(self, db_path: str = None):
        """Initialize storage with database path."""
        self.db_path = db_path or DB_PATH
        self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self):
        """Create data directory if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            # Markets table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS markets (
                    market_id TEXT PRIMARY KEY,
                    question TEXT,
                    category TEXT,
                    volume REAL DEFAULT 0,
                    liquidity REAL DEFAULT 0,
                    outcomes TEXT,
                    outcome_prices TEXT,
                    closed INTEGER DEFAULT 0,
                    resolved INTEGER DEFAULT 0,
                    winner TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TEXT,
                    last_updated TEXT
                )
            """)

            # Wallet-Market positions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wallet_markets (
                    wallet_address TEXT,
                    market_id TEXT,
                    side TEXT,
                    size REAL DEFAULT 0,
                    entry_price REAL DEFAULT 0,
                    volume REAL DEFAULT 0,
                    last_seen TEXT,
                    PRIMARY KEY (wallet_address, market_id)
                )
            """)

            conn.commit()

    def save_market(self, market: Dict) -> None:
        """Save or update a market."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO markets (
                    market_id, question, category, volume, liquidity, outcomes, outcome_prices,
                    closed, resolved, winner, start_date, end_date, created_at, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    market.get("id"),
                    market.get("question"),
                    market.get("category"),
                    market.get("volume", 0),
                    market.get("liquidity", 0),
                    str(market.get("outcomes", [])),
                    str(market.get("outcomePrices", [])),
                    1 if market.get("closed") else 0,
                    1 if market.get("resolved") else 0,
                    market.get("winner"),
                    market.get("startDate"),
                    market.get("endDate"),
                    market.get("createdAt"),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get a market by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM markets WHERE market_id = ?", (market_id,)
            ).fetchone()

            if row:
                return dict(row)
            return None

    def get_active_markets(self) -> List[Dict]:
        """Get all active (unresolved) markets."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM markets WHERE resolved = 0 ORDER BY volume DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def save_wallet_market(
        self, wallet_address: str, market_id: str, position: Dict
    ) -> None:
        """Save or update a wallet's position in a market."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO wallet_markets (
                    wallet_address, market_id, side, size, entry_price, volume, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    wallet_address,
                    market_id,
                    position.get("side"),
                    position.get("size", 0),
                    position.get("price", 0),
                    position.get("size", 0) * position.get("price", 0),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def get_wallets_in_market(self, market_id: str) -> List[str]:
        """Get all wallet addresses that traded in a market."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT wallet_address FROM wallet_markets WHERE market_id = ?",
                (market_id,),
            ).fetchall()
            return [row[0] for row in rows]

    def get_markets_for_wallet(self, wallet_address: str) -> List[Dict]:
        """Get all markets a wallet has traded in."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT m.* FROM markets m
                JOIN wallet_markets wm ON m.market_id = wm.market_id
                WHERE wm.wallet_address = ?
                ORDER BY wm.last_seen DESC
            """,
                (wallet_address,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_wallet_market_position(
        self, wallet_address: str, market_id: str
    ) -> Optional[Dict]:
        """Get a specific wallet's position in a market."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM wallet_markets
                WHERE wallet_address = ? AND market_id = ?
            """,
                (wallet_address, market_id),
            ).fetchone()

            if row:
                return dict(row)
            return None

    def backup(self, backup_dir: Optional[str] = None) -> Optional[str]:
        """Create a backup of the database."""
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(self.db_path) or ".", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"polysuite_{timestamp}.db")
        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info("BACKUP Created: %s", backup_path)
            return backup_path
        except Exception as e:
            logger.warning("BACKUP Failed: %s: %s", type(e).__name__, e)
            return None

    def cleanup_old_backups(
        self, backup_dir: Optional[str] = None, keep_days: int = 7
    ) -> int:
        """Remove backups older than keep_days."""
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(self.db_path) or ".", "backups")
        if not os.path.exists(backup_dir):
            return 0
        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = 0
        for f in os.listdir(backup_dir):
            if not f.startswith("polysuite_") or not f.endswith(".db"):
                continue
            fpath = os.path.join(backup_dir, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    os.remove(fpath)
                    removed += 1
            except Exception:
                continue
        if removed > 0:
            logger.info("BACKUP Cleaned up %s old backups", removed)
        return removed

    def get_db_size(self) -> int:
        """Get database file size in bytes."""
        try:
            return os.path.getsize(self.db_path)
        except Exception:
            return 0

    def get_backup_count(self, backup_dir: Optional[str] = None) -> int:
        """Count existing backups."""
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(self.db_path) or ".", "backups")
        if not os.path.exists(backup_dir):
            return 0
        return sum(
            1
            for f in os.listdir(backup_dir)
            if f.startswith("polysuite_") and f.endswith(".db")
        )
