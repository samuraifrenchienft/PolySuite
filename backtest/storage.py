"""Storage for backtesting: arb_opportunities and alert_log tables."""

import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


class BacktestStorage:
    """Manages arb_opportunities and alert_log for validation."""

    def __init__(self, db_path: str = "data/polysuite.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS arb_opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_id TEXT NOT NULL,
                    question TEXT,
                    yes_price REAL NOT NULL,
                    no_price REAL NOT NULL,
                    total REAL NOT NULL,
                    profit_pct REAL NOT NULL,
                    volume REAL,
                    detected_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT NOT NULL,
                    content_hash TEXT,
                    market_id TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_market ON arb_opportunities(market_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_detected ON arb_opportunities(detected_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_type ON alert_log(alert_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert_log(timestamp)")
            conn.commit()

    def log_arb(self, market_id: str, question: str, yes_price: float, no_price: float,
                profit_pct: float, volume: float = 0) -> bool:
        """Log a detected arbitrage opportunity."""
        total = yes_price + no_price
        ts = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO arb_opportunities (market_id, question, yes_price, no_price, total, profit_pct, volume, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (market_id, question[:200], yes_price, no_price, total, profit_pct, volume, ts),
            )
            conn.commit()
        return True

    def log_alert(self, alert_type: str, content_hash: str = "", market_id: str = "") -> bool:
        """Log an alert for performance tracking."""
        ts = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO alert_log (alert_type, content_hash, market_id, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (alert_type, content_hash[:64], market_id or "", ts),
            )
            conn.commit()
        return True

    def get_arbs_since(self, since_ts: str) -> List[Dict]:
        """Get arb opportunities since timestamp (ISO format)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM arb_opportunities WHERE detected_at >= ? ORDER BY detected_at",
                (since_ts,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_alerts_since(self, since_ts: str, alert_type: str = None) -> List[Dict]:
        """Get alerts since timestamp. Optional filter by alert_type."""
        with self._get_conn() as conn:
            if alert_type:
                rows = conn.execute(
                    "SELECT * FROM alert_log WHERE timestamp >= ? AND alert_type = ? ORDER BY timestamp",
                    (since_ts, alert_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alert_log WHERE timestamp >= ? ORDER BY timestamp",
                    (since_ts,),
                ).fetchall()
            return [dict(r) for r in rows]

    def replay_arbs(self, fee_bps: float = 30) -> Dict:
        """Replay arb opportunities with fee model. Returns summary."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM arb_opportunities ORDER BY detected_at"
            ).fetchall()
        if not rows:
            return {"count": 0, "profitable_after_fee": 0, "total_profit_pct": 0}

        fee_pct = fee_bps / 10000
        profitable = 0
        total_profit = 0.0
        for r in rows:
            profit_pct = float(r["profit_pct"])
            net = profit_pct - (fee_pct * 2)  # buy yes + buy no
            if net > 0:
                profitable += 1
                total_profit += net
        return {
            "count": len(rows),
            "profitable_after_fee": profitable,
            "total_profit_pct": round(total_profit, 4),
        }
