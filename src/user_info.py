"""User info management for PolySuite."""

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class UserInfo:
    """Manages user data, subscriptions, and notification channels."""

    def __init__(self, db_path: str = "data/user_info.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT UNIQUE NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    preferences TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_user_id ON users (user_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    min_liquidity REAL DEFAULT 0,
                    min_edge REAL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    UNIQUE(user_id, bucket)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    channel_type TEXT NOT NULL,
                    channel_value TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    UNIQUE(user_id, channel_type)
                )
            """)

    def add_user(
        self,
        user_id: str,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> bool:
        now = int(time.time())
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (user_id, username, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, display_name, now, now),
                )
                return True
            except sqlite3.IntegrityError:
                conn.execute(
                    "UPDATE users SET username=?, display_name=?, updated_at=? WHERE user_id=?",
                    (username, display_name, now, user_id),
                )
                return True
            except Exception:
                return False

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, username, display_name, created_at, updated_at, preferences FROM users WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "user_id": row[0],
                "username": row[1],
                "display_name": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                "preferences": row[5],
            }

    def update_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        import json

        now = int(time.time())
        prefs_json = json.dumps(preferences)
        with self._connect() as conn:
            try:
                conn.execute(
                    "UPDATE users SET preferences=?, updated_at=? WHERE user_id=?",
                    (prefs_json, now, user_id),
                )
                return True
            except Exception:
                return False

    def add_subscription(
        self, user_id: str, bucket: str, min_liquidity: float = 0, min_edge: float = 0
    ) -> bool:
        now = int(time.time())
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO alert_subscriptions (user_id, bucket, min_liquidity, min_edge, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                    (user_id, bucket, min_liquidity, min_edge, now),
                )
                return True
            except sqlite3.IntegrityError:
                conn.execute(
                    "UPDATE alert_subscriptions SET min_liquidity=?, min_edge=?, enabled=1 WHERE user_id=? AND bucket=?",
                    (min_liquidity, min_edge, user_id, bucket),
                )
                return True
            except Exception:
                return False

    def get_subscriptions(self, user_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT bucket, min_liquidity, min_edge, enabled, created_at FROM alert_subscriptions WHERE user_id=?",
                (user_id,),
            ).fetchall()
            return [
                {
                    "bucket": r[0],
                    "min_liquidity": r[1],
                    "min_edge": r[2],
                    "enabled": bool(r[3]),
                    "created_at": r[4],
                }
                for r in rows
            ]

    def remove_subscription(self, user_id: str, bucket: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM alert_subscriptions WHERE user_id=? AND bucket=?",
                (user_id, bucket),
            )
            return int(cur.rowcount or 0) > 0

    def add_channel(self, user_id: str, channel_type: str, channel_value: str) -> bool:
        now = int(time.time())
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO notification_channels (user_id, channel_type, channel_value, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
                    (user_id, channel_type, channel_value, now),
                )
                return True
            except sqlite3.IntegrityError:
                conn.execute(
                    "UPDATE notification_channels SET channel_value=?, enabled=1 WHERE user_id=? AND channel_type=?",
                    (channel_value, user_id, channel_type),
                )
                return True
            except Exception:
                return False

    def get_channels(self, user_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT channel_type, channel_value, enabled, created_at FROM notification_channels WHERE user_id=?",
                (user_id,),
            ).fetchall()
            return [
                {
                    "channel_type": r[0],
                    "channel_value": r[1],
                    "enabled": bool(r[2]),
                    "created_at": r[3],
                }
                for r in rows
            ]

    def remove_channel(self, user_id: str, channel_type: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM notification_channels WHERE user_id=? AND channel_type=?",
                (user_id, channel_type),
            )
            return int(cur.rowcount or 0) > 0

    def list_users(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, username, display_name, created_at, updated_at FROM users"
            ).fetchall()
            return [
                {
                    "user_id": r[0],
                    "username": r[1],
                    "display_name": r[2],
                    "created_at": r[3],
                    "updated_at": r[4],
                }
                for r in rows
            ]
