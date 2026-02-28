"""Encrypted per-user credential storage for Polymarket and Kalshi.

Schema: user_credentials (user_id TEXT, platform TEXT, encrypted_blob BLOB, created_at TEXT, updated_at TEXT)
user_id = Discord user ID or Telegram user ID (string, e.g. "123456789")
platform = "polymarket" | "kalshi"
encrypted_blob = Fernet.encrypt(json.dumps(creds).encode())
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

DB_PATH = "data/polysuite.db"
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_credentials (
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    encrypted_blob BLOB NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (user_id, platform)
);
"""


def _get_encryption_key() -> bytes:
    """Read CREDENTIAL_ENCRYPTION_KEY from env. Must be valid Fernet key (base64, 32 bytes).
    Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    key = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY not set. Generate with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
        return key.encode() if isinstance(key, str) else key
    except Exception as e:
        raise RuntimeError(f"Invalid CREDENTIAL_ENCRYPTION_KEY: {e}") from e


def _init_db(conn: sqlite3.Connection) -> None:
    """Create user_credentials table if not exists."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn.execute(TABLE_SQL)


class CredentialStore:
    """Encrypted credential storage using SQLite + Fernet."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            _init_db(conn)

    def store_credentials(self, user_id: str, platform: str, creds: dict) -> None:
        """Store encrypted credentials for user/platform."""
        key = _get_encryption_key()
        blob = Fernet(key).encrypt(json.dumps(creds).encode())
        with sqlite3.connect(self.db_path) as conn:
            _init_db(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO user_credentials (user_id, platform, encrypted_blob, created_at, updated_at)
                VALUES (?, ?, ?, datetime('now'), datetime('now'))
                """,
                (str(user_id).strip(), platform.strip().lower(), blob)
            )

    def get_credentials(self, user_id: str, platform: str) -> Optional[dict]:
        """Get decrypted credentials for user/platform. Returns None if not found."""
        key = _get_encryption_key()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT encrypted_blob FROM user_credentials WHERE user_id=? AND platform=?",
                (str(user_id).strip(), platform.strip().lower()),
            )
            row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(Fernet(key).decrypt(row[0]).decode())
        except Exception:
            return None

    def delete_credentials(self, user_id: str, platform: str) -> bool:
        """Delete credentials. Returns True if a row was deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM user_credentials WHERE user_id=? AND platform=?",
                (str(user_id).strip(), platform.strip().lower()),
            )
            return cur.rowcount > 0


# Module-level helpers (use default DB path)
_default_store: Optional[CredentialStore] = None


def _store() -> CredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = CredentialStore()
    return _default_store


def store_credentials(user_id: str, platform: str, creds: dict) -> None:
    """Store credentials (convenience)."""
    _store().store_credentials(user_id, platform, creds)


def get_credentials(user_id: str, platform: str) -> Optional[dict]:
    """Get credentials (convenience)."""
    return _store().get_credentials(user_id, platform)


def delete_credentials(user_id: str, platform: str) -> bool:
    """Delete credentials (convenience)."""
    return _store().delete_credentials(user_id, platform)
