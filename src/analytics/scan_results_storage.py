"""Persist scan results for analytics and strategy insights.

Stores insider, convergence, contrarian scan outputs so we can:
- Track signal volume over time
- Build strategy metrics (hit rate, avg PnL, etc.)
- Surface insights in dashboard
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.paths import DB_PATH


class ScanResultsStorage:
    """Persist and query scan results for analytics."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_type TEXT NOT NULL,
                    scan_ts REAL NOT NULL,
                    count INTEGER DEFAULT 0,
                    payload TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scan_results_type_ts ON scan_results(scan_type, scan_ts)"
            )
            conn.commit()

    def save(
        self,
        scan_type: str,
        scan_ts: float,
        count: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a scan result."""
        payload_json = json.dumps(payload) if payload is not None else None
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scan_results (scan_type, scan_ts, count, payload)
                VALUES (?, ?, ?, ?)
                """,
                (scan_type, scan_ts, count, payload_json),
            )
            conn.commit()

    def get_recent(
        self,
        scan_type: str,
        limit: int = 100,
        since_ts: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent scan results for a type."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            if since_ts is not None:
                rows = conn.execute(
                    """
                    SELECT scan_type, scan_ts, count, payload, created_at
                    FROM scan_results
                    WHERE scan_type = ? AND scan_ts >= ?
                    ORDER BY scan_ts DESC
                    LIMIT ?
                    """,
                    (scan_type, since_ts, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT scan_type, scan_ts, count, payload, created_at
                    FROM scan_results
                    WHERE scan_type = ?
                    ORDER BY scan_ts DESC
                    LIMIT ?
                    """,
                    (scan_type, limit),
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("payload"):
                try:
                    d["payload"] = json.loads(d["payload"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(d)
        return out

    def get_metrics(
        self,
        scan_type: str,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """Aggregate metrics for a scan type over the last N hours."""
        import time
        since = time.time() - (hours * 3600)
        rows = self.get_recent(scan_type, limit=1000, since_ts=since)
        if not rows:
            return {"scan_type": scan_type, "hours": hours, "runs": 0, "avg_count": 0}
        total_count = sum(r.get("count", 0) for r in rows)
        return {
            "scan_type": scan_type,
            "hours": hours,
            "runs": len(rows),
            "avg_count": round(total_count / len(rows), 1) if rows else 0,
            "total_signals": total_count,
        }
