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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT NOT NULL,
                    alert_ts REAL NOT NULL,
                    market_id TEXT,
                    wallet_address TEXT,
                    confidence TEXT,
                    sent_discord INTEGER DEFAULT 0,
                    sent_telegram INTEGER DEFAULT 0,
                    payload TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_events_type_ts ON alert_events(alert_type, alert_ts)"
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

    def save_alert_event(
        self,
        alert_type: str,
        alert_ts: float,
        market_id: Optional[str] = None,
        wallet_address: Optional[str] = None,
        confidence: Optional[str] = None,
        sent_discord: bool = False,
        sent_telegram: bool = False,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a sent alert event for future outcome scoring."""
        payload_json = json.dumps(payload) if payload is not None else None
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO alert_events
                (alert_type, alert_ts, market_id, wallet_address, confidence, sent_discord, sent_telegram, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_type,
                    alert_ts,
                    market_id,
                    wallet_address,
                    confidence,
                    1 if sent_discord else 0,
                    1 if sent_telegram else 0,
                    payload_json,
                ),
            )
            conn.commit()

    def get_alert_event_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """Aggregate sent alert counts by type over a lookback window."""
        import time

        since = time.time() - (hours * 3600)
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT alert_type, COUNT(*) AS n
                FROM alert_events
                WHERE alert_ts >= ?
                GROUP BY alert_type
                ORDER BY n DESC
                """,
                (since,),
            ).fetchall()
        by_type = {r[0]: int(r[1]) for r in rows}
        return {
            "hours": hours,
            "total_sent": int(sum(by_type.values())),
            "by_type": by_type,
        }

    def build_digest_text(self, hours: int = 24) -> str:
        """Build a plain-text strategy digest scaffold from scan and alert metrics."""
        insider = self.get_metrics("insider", hours=hours)
        conv = self.get_metrics("convergence", hours=hours)
        contra = self.get_metrics("contrarian", hours=hours)
        sent = self.get_alert_event_metrics(hours=hours)
        lines = [
            f"Strategy Digest ({hours}h)",
            f"- Insider scans: runs={insider.get('runs', 0)}, signals={insider.get('total_signals', 0)}, avg={insider.get('avg_count', 0)}",
            f"- Convergence scans: runs={conv.get('runs', 0)}, signals={conv.get('total_signals', 0)}, avg={conv.get('avg_count', 0)}",
            f"- Contrarian scans: runs={contra.get('runs', 0)}, signals={contra.get('total_signals', 0)}, avg={contra.get('avg_count', 0)}",
            f"- Sent alerts: total={sent.get('total_sent', 0)}, by_type={sent.get('by_type', {})}",
        ]
        return "\n".join(lines)
