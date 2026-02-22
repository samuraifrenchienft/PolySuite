"""SQLite storage for wallet data."""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional
from src.wallet import Wallet
from src.wallet.portfolio import Portfolio
from src.wallet.portfolio_calculator import PortfolioCalculator


class WalletStorage:
    """Manages SQLite database for wallet storage."""

    def __init__(
        self,
        db_path: str = "data/polysuite.db",
        conn: Optional[sqlite3.Connection] = None,
    ):
        """Initialize storage with database path."""
        self.db_path = db_path
        self._conn = conn
        if not self._conn:
            self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self):
        """Create data directory if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        if self._conn:
            return self._conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY,
                    nickname TEXT NOT NULL,
                    total_trades INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0.0,
                    last_updated TEXT,
                    created_at TEXT,
                    is_smart_money BOOLEAN DEFAULT FALSE,
                    trade_volume INTEGER DEFAULT 0
                )
            """)

            # Migration: Add missing columns if they don't exist
            try:
                conn.execute(
                    "ALTER TABLE wallets ADD COLUMN is_smart_money BOOLEAN DEFAULT FALSE"
                )
            except:
                pass
            try:
                conn.execute(
                    "ALTER TABLE wallets ADD COLUMN trade_volume INTEGER DEFAULT 0"
                )
            except:
                pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS wallet_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT,
                    timestamp TEXT,
                    total_trades INTEGER,
                    wins INTEGER,
                    win_rate REAL,
                    total_volume INTEGER,
                    FOREIGN KEY (wallet_address) REFERENCES wallets (address) ON DELETE CASCADE
                )
            """)

            conn.commit()

    def add_wallet(self, wallet: Wallet) -> bool:
        """Add a wallet to tracking. Returns True if added, False if exists."""
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO wallets (address, nickname, total_trades, wins, win_rate, last_updated, created_at, is_smart_money, trade_volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        wallet.address,
                        wallet.nickname,
                        wallet.total_trades,
                        wallet.wins,
                        wallet.win_rate,
                        wallet.last_updated,
                        wallet.created_at,
                        wallet.is_smart_money,
                        wallet.trade_volume,
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def remove_wallet(self, address: str) -> bool:
        """Remove a wallet from tracking. Returns True if removed."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM wallets WHERE address = ?", (address,))
            conn.commit()
            return cursor.rowcount > 0

    def get_portfolio(self, address: str, api_factory) -> Optional[Portfolio]:
        """Get a wallet's portfolio by address."""
        wallet = self.get_wallet(address)
        if not wallet:
            return None

        calculator = PortfolioCalculator(api_factory)
        return calculator.calculate_portfolio(address, wallet.nickname)

    def get_wallet(self, address: str) -> Optional[Wallet]:
        """Get a wallet by address."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM wallets WHERE address = ?", (address,)
            ).fetchone()
            if row:
                return Wallet(
                    address=row["address"],
                    nickname=row["nickname"],
                    total_trades=row["total_trades"],
                    wins=row["wins"],
                    win_rate=row["win_rate"],
                    last_updated=row["last_updated"],
                    created_at=row["created_at"],
                    is_smart_money=row["is_smart_money"],
                    trade_volume=row["trade_volume"],
                )
            return None

    def list_wallets(
        self, min_trades: Optional[int] = None, min_volume: Optional[int] = None
    ) -> List[Wallet]:
        """List all tracked wallets, with optional filters."""
        query = "SELECT * FROM wallets"
        filters = []
        params = []

        if min_trades is not None:
            filters.append("total_trades >= ?")
            params.append(min_trades)

        if min_volume is not None:
            filters.append("trade_volume >= ?")
            params.append(min_volume)

        if filters:
            query += " WHERE " + " AND ".join(filters)

        query += " ORDER BY nickname"

        with self._get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                Wallet(
                    address=row["address"],
                    nickname=row["nickname"],
                    total_trades=row["total_trades"],
                    wins=row["wins"],
                    win_rate=row["win_rate"],
                    last_updated=row["last_updated"],
                    created_at=row["created_at"],
                    is_smart_money=row["is_smart_money"],
                    trade_volume=row["trade_volume"],
                )
                for row in rows
            ]

    def log_wallet_history(self, wallet: Wallet):
        """Log a snapshot of the wallet's current stats."""
        from datetime import datetime

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO wallet_history (wallet_address, timestamp, total_trades, wins, win_rate, total_volume)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    wallet.address,
                    datetime.utcnow().isoformat(),
                    wallet.total_trades,
                    wallet.wins,
                    wallet.win_rate,
                    wallet.trade_volume,
                ),
            )
            conn.commit()

    def update_wallet_stats(
        self, address: str, total_trades: int, wins: int, trade_volume: int
    ) -> bool:
        """Update wallet trading stats."""
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        from datetime import datetime

        last_updated = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE wallets
                SET total_trades = ?, wins = ?, win_rate = ?, last_updated = ?, trade_volume = ?
                WHERE address = ?
            """,
                (total_trades, wins, win_rate, last_updated, trade_volume, address),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_high_performers(self, threshold: float = 55.0) -> List[Wallet]:
        """Get wallets above win rate threshold with minimum 10 trades."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM wallets
                WHERE win_rate >= ? AND total_trades >= 10
                ORDER BY win_rate DESC
            """,
                (threshold,),
            ).fetchall()
            return [
                Wallet(
                    address=row["address"],
                    nickname=row["nickname"],
                    total_trades=row["total_trades"],
                    wins=row["wins"],
                    win_rate=row["win_rate"],
                    last_updated=row["last_updated"],
                    created_at=row["created_at"],
                    is_smart_money=row["is_smart_money"],
                )
                for row in rows
            ]

    def flag_smart_money_wallet(self, address: str) -> bool:
        """Flag a wallet as smart money."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE wallets
                SET is_smart_money = TRUE
                WHERE address = ?
            """,
                (address,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_wallet_history(self, address: str) -> List[dict]:
        """Get the performance history for a given wallet."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, total_trades, wins, win_rate, total_volume
                FROM wallet_history
                WHERE wallet_address = ?
                ORDER BY timestamp DESC
            """,
                (address,),
            ).fetchall()

        return [
            {
                "timestamp": row["timestamp"],
                "total_trades": row["total_trades"],
                "wins": row["wins"],
                "win_rate": row["win_rate"],
                "total_volume": row["total_volume"],
            }
            for row in rows
        ]

    def backup(self, backup_dir: str = None) -> str:
        """Create a backup of the database."""
        import os
        import shutil
        from datetime import datetime

        if backup_dir is None:
            backup_dir = os.path.join(
                os.path.dirname(self.db_path) or "data", "backups"
            )
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"wallets_{timestamp}.db")
        try:
            shutil.copy2(self.db_path, backup_path)
            print(f"[BACKUP] Created: {backup_path}")
            return backup_path
        except Exception as e:
            print(f"[BACKUP] Failed: {type(e).__name__}: {e}")
            return None

    def cleanup_old_backups(self, backup_dir: str = None, keep_days: int = 7) -> int:
        """Remove backups older than keep_days."""
        import os
        from datetime import datetime, timedelta

        if backup_dir is None:
            backup_dir = os.path.join(
                os.path.dirname(self.db_path) or "data", "backups"
            )
        if not os.path.exists(backup_dir):
            return 0
        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = 0
        for f in os.listdir(backup_dir):
            if not f.startswith("wallets_") or not f.endswith(".db"):
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
            print(f"[BACKUP] Cleaned up {removed} old backups")
        return removed

    def get_db_size(self) -> int:
        """Get database file size in bytes."""
        import os

        try:
            return os.path.getsize(self.db_path)
        except Exception:
            return 0

    def get_backup_count(self, backup_dir: str = None) -> int:
        """Count existing backups."""
        import os

        if backup_dir is None:
            backup_dir = os.path.join(
                os.path.dirname(self.db_path) or "data", "backups"
            )
        if not os.path.exists(backup_dir):
            return 0
        return sum(
            1
            for f in os.listdir(backup_dir)
            if f.startswith("wallets_") and f.endswith(".db")
        )
