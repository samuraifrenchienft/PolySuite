"""SQLite storage for wallet data."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from src.config.paths import DB_PATH
from src.wallet import Wallet
from src.wallet.portfolio import Portfolio
from src.wallet.portfolio_calculator import PortfolioCalculator

logger = logging.getLogger(__name__)


class WalletStorage:
    """Manages SQLite database for wallet storage."""

    def __init__(
        self,
        db_path: str = None,
        conn: Optional[sqlite3.Connection] = None,
    ):
        """Initialize storage with database path."""
        self.db_path = db_path or DB_PATH
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
                    trade_volume INTEGER DEFAULT 0,
                    bot_score INTEGER,
                    unresolved_exposure_usd REAL,
                    last_vetted_at TEXT,
                    total_pnl REAL,
                    roi_pct REAL,
                    conviction_score REAL,
                    is_specialty BOOLEAN DEFAULT FALSE,
                    specialty_note TEXT,
                    specialty_market_id TEXT,
                    specialty_category TEXT
                )
            """)

            # Migration: Add missing columns if they don't exist
            for col, sql in [
                (
                    "is_smart_money",
                    "ALTER TABLE wallets ADD COLUMN is_smart_money BOOLEAN DEFAULT FALSE",
                ),
                (
                    "trade_volume",
                    "ALTER TABLE wallets ADD COLUMN trade_volume INTEGER DEFAULT 0",
                ),
                ("bot_score", "ALTER TABLE wallets ADD COLUMN bot_score INTEGER"),
                (
                    "unresolved_exposure_usd",
                    "ALTER TABLE wallets ADD COLUMN unresolved_exposure_usd REAL",
                ),
                (
                    "last_vetted_at",
                    "ALTER TABLE wallets ADD COLUMN last_vetted_at TEXT",
                ),
                ("total_pnl", "ALTER TABLE wallets ADD COLUMN total_pnl REAL"),
                ("roi_pct", "ALTER TABLE wallets ADD COLUMN roi_pct REAL"),
                (
                    "conviction_score",
                    "ALTER TABLE wallets ADD COLUMN conviction_score REAL",
                ),
                (
                    "is_specialty",
                    "ALTER TABLE wallets ADD COLUMN is_specialty BOOLEAN DEFAULT FALSE",
                ),
                (
                    "specialty_note",
                    "ALTER TABLE wallets ADD COLUMN specialty_note TEXT",
                ),
                (
                    "specialty_market_id",
                    "ALTER TABLE wallets ADD COLUMN specialty_market_id TEXT",
                ),
                (
                    "specialty_category",
                    "ALTER TABLE wallets ADD COLUMN specialty_category TEXT",
                ),
                (
                    "classification",
                    "ALTER TABLE wallets ADD COLUMN classification TEXT",
                ),
                (
                    "classification_reason",
                    "ALTER TABLE wallets ADD COLUMN classification_reason TEXT",
                ),
                (
                    "total_score",
                    "ALTER TABLE wallets ADD COLUMN total_score REAL DEFAULT 0",
                ),
                (
                    "is_bot",
                    "ALTER TABLE wallets ADD COLUMN is_bot BOOLEAN DEFAULT FALSE",
                ),
                (
                    "is_farmer",
                    "ALTER TABLE wallets ADD COLUMN is_farmer BOOLEAN DEFAULT FALSE",
                ),
                (
                    "is_high_loss_rate",
                    "ALTER TABLE wallets ADD COLUMN is_high_loss_rate BOOLEAN DEFAULT FALSE",
                ),
                (
                    "current_win_streak",
                    "ALTER TABLE wallets ADD COLUMN current_win_streak INTEGER DEFAULT 0",
                ),
                (
                    "max_win_streak",
                    "ALTER TABLE wallets ADD COLUMN max_win_streak INTEGER DEFAULT 0",
                ),
                (
                    "stats_7d_volume",
                    "ALTER TABLE wallets ADD COLUMN stats_7d_volume REAL DEFAULT 0",
                ),
                (
                    "stats_7d_win_rate",
                    "ALTER TABLE wallets ADD COLUMN stats_7d_win_rate REAL DEFAULT 0",
                ),
                (
                    "stats_14d_volume",
                    "ALTER TABLE wallets ADD COLUMN stats_14d_volume REAL DEFAULT 0",
                ),
                (
                    "stats_14d_win_rate",
                    "ALTER TABLE wallets ADD COLUMN stats_14d_win_rate REAL DEFAULT 0",
                ),
                # Tier system
                ("tier", "ALTER TABLE wallets ADD COLUMN tier TEXT DEFAULT 'watch'"),
                (
                    "tier_changed_at",
                    "ALTER TABLE wallets ADD COLUMN tier_changed_at TEXT",
                ),
                (
                    "tier_change_reason",
                    "ALTER TABLE wallets ADD COLUMN tier_change_reason TEXT",
                ),
                # Scoring
                ("score_7d", "ALTER TABLE wallets ADD COLUMN score_7d REAL DEFAULT 0"),
                (
                    "score_14d",
                    "ALTER TABLE wallets ADD COLUMN score_14d REAL DEFAULT 0",
                ),
                (
                    "score_30d",
                    "ALTER TABLE wallets ADD COLUMN score_30d REAL DEFAULT 0",
                ),
                (
                    "last_scored_at",
                    "ALTER TABLE wallets ADD COLUMN last_scored_at TEXT",
                ),
                # Streaks and activity
                (
                    "consecutive_losses",
                    "ALTER TABLE wallets ADD COLUMN consecutive_losses INTEGER DEFAULT 0",
                ),
                (
                    "max_consecutive_losses",
                    "ALTER TABLE wallets ADD COLUMN max_consecutive_losses INTEGER DEFAULT 0",
                ),
                ("last_trade_at", "ALTER TABLE wallets ADD COLUMN last_trade_at TEXT"),
                (
                    "days_inactive",
                    "ALTER TABLE wallets ADD COLUMN days_inactive INTEGER DEFAULT 0",
                ),
                # Category specialization
                (
                    "specialty_category_2",
                    "ALTER TABLE wallets ADD COLUMN specialty_category_2 TEXT",
                ),
                (
                    "specialty_win_rate",
                    "ALTER TABLE wallets ADD COLUMN specialty_win_rate REAL DEFAULT 0",
                ),
                (
                    "specialty_volume",
                    "ALTER TABLE wallets ADD COLUMN specialty_volume REAL DEFAULT 0",
                ),
                # Betting patterns
                (
                    "avg_hold_duration_hours",
                    "ALTER TABLE wallets ADD COLUMN avg_hold_duration_hours REAL DEFAULT 0",
                ),
                (
                    "preferred_odds_range",
                    "ALTER TABLE wallets ADD COLUMN preferred_odds_range TEXT DEFAULT 'medium'",
                ),
                (
                    "size_consistency",
                    "ALTER TABLE wallets ADD COLUMN size_consistency REAL DEFAULT 0",
                ),
                # Volume-weighted metrics
                (
                    "volume_weighted_win_rate",
                    "ALTER TABLE wallets ADD COLUMN volume_weighted_win_rate REAL DEFAULT 0",
                ),
                (
                    "recent_7d_volume",
                    "ALTER TABLE wallets ADD COLUMN recent_7d_volume REAL DEFAULT 0",
                ),
                (
                    "recent_14d_volume",
                    "ALTER TABLE wallets ADD COLUMN recent_14d_volume REAL DEFAULT 0",
                ),
                (
                    "recent_7d_trades",
                    "ALTER TABLE wallets ADD COLUMN recent_7d_trades INTEGER DEFAULT 0",
                ),
                (
                    "recent_14d_trades",
                    "ALTER TABLE wallets ADD COLUMN recent_14d_trades INTEGER DEFAULT 0",
                ),
                (
                    "recent_7d_win_rate",
                    "ALTER TABLE wallets ADD COLUMN recent_7d_win_rate REAL DEFAULT 0",
                ),
                (
                    "recent_14d_win_rate",
                    "ALTER TABLE wallets ADD COLUMN recent_14d_win_rate REAL DEFAULT 0",
                ),
                (
                    "recent_7d_pnl",
                    "ALTER TABLE wallets ADD COLUMN recent_7d_pnl REAL DEFAULT 0",
                ),
                (
                    "recent_14d_pnl",
                    "ALTER TABLE wallets ADD COLUMN recent_14d_pnl REAL DEFAULT 0",
                ),
                # Pattern tracking
                (
                    "trading_hours",
                    "ALTER TABLE wallets ADD COLUMN trading_hours TEXT DEFAULT '{}'",
                ),
                (
                    "trading_days",
                    "ALTER TABLE wallets ADD COLUMN trading_days TEXT DEFAULT '{}'",
                ),
                (
                    "odds_distribution",
                    "ALTER TABLE wallets ADD COLUMN odds_distribution TEXT DEFAULT '{}'",
                ),
                (
                    "category_stats",
                    "ALTER TABLE wallets ADD COLUMN category_stats TEXT DEFAULT '{}'",
                ),
                (
                    "is_win_streak_badge",
                    "ALTER TABLE wallets ADD COLUMN is_win_streak_badge BOOLEAN DEFAULT FALSE",
                ),
                (
                    "specialty_roi_pct",
                    "ALTER TABLE wallets ADD COLUMN specialty_roi_pct REAL",
                ),
            ]:
                try:
                    conn.execute(sql)
                except Exception:
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

            # Scoring history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scoring_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT,
                    scored_at TEXT,
                    composite_score REAL,
                    win_rate REAL,
                    streak INTEGER,
                    tier TEXT,
                    FOREIGN KEY (wallet_address) REFERENCES wallets(address) ON DELETE CASCADE
                )
            """)

            # Tier change log table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tier_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT,
                    changed_at TEXT,
                    old_tier TEXT,
                    new_tier TEXT,
                    reason TEXT,
                    score_at_change REAL,
                    FOREIGN KEY (wallet_address) REFERENCES wallets(address) ON DELETE CASCADE
                )
            """)

            conn.commit()

    def add_wallet(self, wallet: Wallet) -> bool:
        """Add a wallet to tracking. Returns True if added, False if exists."""
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO wallets (address, nickname, total_trades, wins, win_rate, last_updated, created_at, is_smart_money, trade_volume, bot_score, unresolved_exposure_usd, last_vetted_at, total_pnl, roi_pct, conviction_score, is_specialty, specialty_note, specialty_market_id, specialty_category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        getattr(wallet, "bot_score", None),
                        getattr(wallet, "unresolved_exposure_usd", None),
                        getattr(wallet, "last_vetted_at", None),
                        getattr(wallet, "total_pnl", None),
                        getattr(wallet, "roi_pct", None),
                        getattr(wallet, "conviction_score", None),
                        getattr(wallet, "is_specialty", False),
                        getattr(wallet, "specialty_note", None),
                        getattr(wallet, "specialty_market_id", None),
                        getattr(wallet, "specialty_category", None),
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
            ok = cursor.rowcount > 0
        if ok:
            try:
                from src.copy.storage import remove_copy_target

                remove_copy_target(address)
            except Exception:
                pass
        return ok

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
                return Wallet.from_dict(dict(row))
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
            return [Wallet.from_dict(dict(row)) for row in rows]

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
        self,
        address: str,
        total_trades: int,
        wins: int,
        trade_volume: int,
        win_rate: Optional[float] = None,
    ) -> bool:
        """Update wallet trading stats.

        If ``win_rate`` is None, it is computed as ``wins / total_trades * 100`` (legacy).
        Pass an explicit rate when ``wins`` are resolved wins but ``total_trades`` is all fills.
        """
        if win_rate is None:
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

    def update_wallet_vetting(
        self,
        address: str,
        bot_score: Optional[int] = None,
        unresolved_exposure_usd: Optional[float] = None,
        total_pnl: Optional[float] = None,
        roi_pct: Optional[float] = None,
        conviction_score: Optional[float] = None,
        is_specialty: bool = False,
        specialty_note: Optional[str] = None,
        specialty_market_id: Optional[str] = None,
        specialty_category: Optional[str] = None,
        specialty_roi_pct: Optional[float] = None,
        is_win_streak_badge: bool = False,
        tier: Optional[str] = None,
        total_trades: Optional[int] = None,
        wins: Optional[int] = None,
        win_rate: Optional[float] = None,
        trade_volume: Optional[float] = None,
    ) -> bool:
        """Persist vetting results (bot_score, specialty, tier when passed, etc.)."""
        from datetime import datetime

        last_vetted_at = datetime.utcnow().isoformat()
        updates = [
            "bot_score = ?", "unresolved_exposure_usd = ?", "last_vetted_at = ?",
            "total_pnl = ?", "roi_pct = ?", "conviction_score = ?",
            "is_specialty = ?", "specialty_note = ?", "specialty_market_id = ?",
            "specialty_category = ?", "specialty_roi_pct = ?", "is_win_streak_badge = ?"
        ]
        values = [
            bot_score, unresolved_exposure_usd, last_vetted_at,
            total_pnl, roi_pct, conviction_score,
            is_specialty, specialty_note, specialty_market_id,
            specialty_category, specialty_roi_pct, is_win_streak_badge,
        ]
        if tier and tier in ("watch", "vetted", "elite"):
            updates.append("tier = ?")
            values.append(tier)
        if total_trades is not None:
            updates.append("total_trades = ?")
            values.append(total_trades)
        if wins is not None:
            updates.append("wins = ?")
            values.append(wins)
        if win_rate is not None:
            updates.append("win_rate = ?")
            values.append(win_rate)
        if trade_volume is not None:
            updates.append("trade_volume = ?")
            values.append(trade_volume)
        values.append(address)
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE wallets SET {', '.join(updates)} WHERE address = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_wallet(self, wallet: Wallet) -> bool:
        """Update a wallet with all fields from a Wallet object."""
        from datetime import datetime

        data = wallet.to_dict()
        if not data:
            return False

        # Build dynamic update query
        fields = []
        values = []
        for key, value in data.items():
            if key in ("address", "nickname"):
                continue
            fields.append(f"{key} = ?")
            values.append(value)

        if not fields:
            return False

        values.append(wallet.address)

        query = f"UPDATE wallets SET {', '.join(fields)} WHERE address = ?"

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, values)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.warning("Storage: Error updating wallet: %s", e)
            return False

    def get_high_performers(
        self, threshold: float = 55.0, max_bot_score: int = 70
    ) -> List[Wallet]:
        """Get wallets above win rate threshold, min 10 trades, bot_score < max_bot_score."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM wallets
                WHERE win_rate >= ? AND total_trades >= 10
                  AND (bot_score IS NULL OR bot_score < ?)
                ORDER BY win_rate DESC
            """,
                (threshold, max_bot_score),
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
                    trade_volume=row["trade_volume"]
                    if "trade_volume" in row.keys()
                    else 0,
                    bot_score=row["bot_score"] if "bot_score" in row.keys() else None,
                    unresolved_exposure_usd=row["unresolved_exposure_usd"]
                    if "unresolved_exposure_usd" in row.keys()
                    else None,
                    last_vetted_at=row["last_vetted_at"]
                    if "last_vetted_at" in row.keys()
                    else None,
                    total_pnl=row["total_pnl"] if "total_pnl" in row.keys() else None,
                    roi_pct=row["roi_pct"] if "roi_pct" in row.keys() else None,
                    conviction_score=row["conviction_score"]
                    if "conviction_score" in row.keys()
                    else None,
                    is_specialty=bool(row["is_specialty"])
                    if "is_specialty" in row.keys()
                    else False,
                    specialty_note=row["specialty_note"]
                    if "specialty_note" in row.keys()
                    else None,
                    specialty_market_id=row["specialty_market_id"]
                    if "specialty_market_id" in row.keys()
                    else None,
                    specialty_category=row["specialty_category"]
                    if "specialty_category" in row.keys()
                    else None,
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
            logger.info("BACKUP Created: %s", backup_path)
            return backup_path
        except Exception as e:
            logger.warning("BACKUP Failed: %s: %s", type(e).__name__, e)
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
            logger.info("BACKUP Cleaned up %s old backups", removed)
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

    # ============ TIER MANAGEMENT METHODS ============

    def change_tier(self, address: str, new_tier: str, reason: str) -> bool:
        """Change wallet tier and log the change."""
        from datetime import datetime

        wallet = self.get_wallet(address)
        if not wallet:
            return False

        old_tier = wallet.tier
        if old_tier == new_tier:
            return True

        with self._get_connection() as conn:
            conn.execute(
                """UPDATE wallets SET tier = ?, tier_changed_at = ?, tier_change_reason = ? WHERE address = ?""",
                (new_tier, datetime.utcnow().isoformat(), reason, address),
            )

            conn.execute(
                """INSERT INTO tier_log (wallet_address, changed_at, old_tier, new_tier, reason, score_at_change)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    address,
                    datetime.utcnow().isoformat(),
                    old_tier,
                    new_tier,
                    reason,
                    wallet.total_score,
                ),
            )
            conn.commit()

        return True

    def log_scoring(self, wallet: Wallet):
        """Log a scoring snapshot."""
        from datetime import datetime

        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO scoring_history (wallet_address, scored_at, composite_score, win_rate, streak, tier)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    wallet.address,
                    datetime.utcnow().isoformat(),
                    wallet.total_score,
                    wallet.win_rate,
                    wallet.current_win_streak,
                    wallet.tier,
                ),
            )
            conn.commit()

    def get_wallets_by_tier(self, tier: str) -> List[Wallet]:
        """Get all wallets in a specific tier."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM wallets WHERE tier = ? ORDER BY total_score DESC",
                (tier,),
            )
            rows = cursor.fetchall()
            return [self._row_to_wallet(row) for row in rows]

    def get_tier_log(self, address: str, limit: int = 10) -> List[dict]:
        """Get tier change history for a wallet."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM tier_log WHERE wallet_address = ? ORDER BY changed_at DESC LIMIT ?""",
                (address, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_scoring_history(self, address: str, limit: int = 30) -> List[dict]:
        """Get scoring history for a wallet."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM scoring_history WHERE wallet_address = ? ORDER BY scored_at DESC LIMIT ?""",
                (address, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all_wallets_with_scores(self) -> List[Wallet]:
        """Get all wallets with scores for processing."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM wallets WHERE total_score > 0 ORDER BY total_score DESC"
            )
            return [self._row_to_wallet(row) for row in cursor.fetchall()]

    def _row_to_wallet(self, row: sqlite3.Row) -> Wallet:
        """Convert a database row to a Wallet object."""
        data = dict(row)
        return Wallet.from_dict(data)
