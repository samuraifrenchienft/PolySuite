"""Backup utility for PolySuite database."""

import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path


class BackupManager:
    """Manages database backups with rotation."""

    def __init__(
        self, db_path: str = "data/predictionsuite.db", backup_dir: str = "backups"
    ):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.max_backups = 7  # Keep last 7 backups

    def _ensure_backup_dir(self):
        """Create backup directory if it doesn't exist."""
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def backup(self) -> str:
        """Create a backup of the database."""
        self._ensure_backup_dir()

        if not os.path.exists(self.db_path):
            print(f"[Backup] Database not found: {self.db_path}")
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.backup_dir}/predictionsuite_{timestamp}.db"

        try:
            conn = sqlite3.connect(self.db_path)
            backup_conn = sqlite3.connect(backup_path)
            conn.backup(backup_conn)
            conn.close()
            backup_conn.close()
            print(f"[Backup] Created: {backup_path}")

            # Rotate old backups
            self._rotate_backups()

            return backup_path
        except Exception as e:
            print(f"[Backup] Error: {e}")
            return ""

    def _rotate_backups(self):
        """Keep only the last N backups."""
        try:
            backups = sorted(
                [f for f in os.listdir(self.backup_dir) if f.endswith(".db")],
                key=lambda x: os.path.getmtime(f"{self.backup_dir}/{x}"),
            )

            while len(backups) > self.max_backups:
                old = backups.pop(0)
                os.remove(f"{self.backup_dir}/{old}")
                print(f"[Backup] Deleted old: {old}")
        except Exception as e:
            print(f"[Backup] Rotation error: {e}")

    def list_backups(self) -> list:
        """List all available backups."""
        if not os.path.exists(self.backup_dir):
            return []

        backups = sorted(
            [f for f in os.listdir(self.backup_dir) if f.endswith(".db")], reverse=True
        )
        return backups

    def restore(self, backup_name: str) -> bool:
        """Restore database from a backup."""
        backup_path = f"{self.backup_dir}/{backup_name}"

        if not os.path.exists(backup_path):
            print(f"[Backup] Not found: {backup_path}")
            return False

        try:
            # Close any existing connections
            conn = sqlite3.connect(self.db_path)
            conn.close()

            # Restore
            shutil.copy2(backup_path, self.db_path)
            print(f"[Backup] Restored from: {backup_name}")
            return True
        except Exception as e:
            print(f"[Backup] Restore error: {e}")
            return False
