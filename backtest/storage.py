"""Storage for backtesting and suggestion outcome tracking."""

import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


class BacktestStorage:
    """Manages arb_opportunities, alert_log, and suggestion tracking."""

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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS suggestion_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    category TEXT,
                    market_id TEXT NOT NULL,
                    question TEXT,
                    side TEXT NOT NULL,
                    entry_price REAL,
                    conviction TEXT,
                    entry_reason TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    winner TEXT,
                    resolved_at TEXT,
                    pnl_usd REAL,
                    metadata_json TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_market ON arb_opportunities(market_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_arb_detected ON arb_opportunities(detected_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_type ON alert_log(alert_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert_log(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestion_market ON suggestion_log(market_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestion_status ON suggestion_log(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_suggestion_ts ON suggestion_log(timestamp)")
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

    def log_suggestion(
        self,
        source: str,
        category: str,
        market_id: str,
        question: str,
        side: str,
        entry_price: Optional[float] = None,
        conviction: str = "",
        entry_reason: str = "",
        metadata_json: str = "",
        dedupe_window_seconds: int = 21600,
    ) -> bool:
        """Log actionable AI suggestion. Dedupe same market+side within window."""
        if not market_id:
            return False
        side_norm = (side or "").strip().upper()
        if side_norm not in ("YES", "NO"):
            return False
        now = datetime.utcnow()
        ts = now.isoformat()
        with self._get_conn() as conn:
            recent = conn.execute(
                """
                SELECT id FROM suggestion_log
                WHERE market_id = ? AND side = ?
                  AND (strftime('%s','now') - strftime('%s', timestamp)) <= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (market_id, side_norm, int(dedupe_window_seconds)),
            ).fetchone()
            if recent:
                return False
            conn.execute(
                """
                INSERT INTO suggestion_log
                (source, category, market_id, question, side, entry_price, conviction, entry_reason, metadata_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (source or "unknown")[:32],
                    (category or "other")[:32],
                    str(market_id)[:128],
                    (question or "")[:240],
                    side_norm,
                    float(entry_price) if entry_price is not None else None,
                    (conviction or "")[:24],
                    (entry_reason or "")[:240],
                    (metadata_json or "")[:1000],
                    ts,
                ),
            )
            conn.commit()
        return True

    @staticmethod
    def _winner_to_side(winner) -> Optional[str]:
        """Normalize winner values from API to YES/NO."""
        if winner is None:
            return None
        w = str(winner).strip().lower()
        if w in ("yes", "true", "1"):
            return "YES"
        if w in ("no", "false", "0"):
            return "NO"
        return None

    def resolve_open_suggestions(
        self, polymarket_api, stake_usd: float = 100.0, max_per_run: int = 100
    ) -> Dict:
        """Resolve open suggestions using market status from API."""
        resolved = wins = losses = unresolved_checked = 0
        if not polymarket_api:
            return {"resolved": 0, "wins": 0, "losses": 0, "checked": 0}

        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, market_id, side
                FROM suggestion_log
                WHERE status = 'open'
                ORDER BY id ASC
                LIMIT ?
                """,
                (int(max_per_run),),
            ).fetchall()

            for r in rows:
                unresolved_checked += 1
                try:
                    details = polymarket_api.get_market_details(r["market_id"]) or {}
                except Exception:
                    continue
                winner_side = self._winner_to_side(details.get("winner"))
                if not winner_side:
                    continue
                is_win = winner_side == str(r["side"]).upper()
                pnl = float(stake_usd if is_win else -stake_usd)
                conn.execute(
                    """
                    UPDATE suggestion_log
                    SET status = 'resolved',
                        winner = ?,
                        resolved_at = ?,
                        pnl_usd = ?
                    WHERE id = ?
                    """,
                    (winner_side, datetime.utcnow().isoformat(), pnl, r["id"]),
                )
                resolved += 1
                if is_win:
                    wins += 1
                else:
                    losses += 1
            conn.commit()
        return {
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "checked": unresolved_checked,
        }

    def get_suggestion_summary(self, since_ts: str) -> Dict:
        """Return summary stats for suggestions created since timestamp."""
        with self._get_conn() as conn:
            totals = conn.execute(
                """
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved,
                  SUM(CASE WHEN status='resolved' AND pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
                  SUM(CASE WHEN status='resolved' AND pnl_usd < 0 THEN 1 ELSE 0 END) AS losses,
                  SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_count,
                  COALESCE(SUM(CASE WHEN status='resolved' THEN pnl_usd ELSE 0 END), 0) AS pnl_usd
                FROM suggestion_log
                WHERE timestamp >= ?
                """,
                (since_ts,),
            ).fetchone()
            by_category_rows = conn.execute(
                """
                SELECT category,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='resolved' AND pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status='resolved' AND pnl_usd < 0 THEN 1 ELSE 0 END) AS losses,
                       COALESCE(SUM(CASE WHEN status='resolved' THEN pnl_usd ELSE 0 END), 0) AS pnl_usd
                FROM suggestion_log
                WHERE timestamp >= ?
                GROUP BY category
                ORDER BY total DESC
                """,
                (since_ts,),
            ).fetchall()

        total = int(totals["total"] or 0)
        resolved = int(totals["resolved"] or 0)
        wins = int(totals["wins"] or 0)
        losses = int(totals["losses"] or 0)
        open_count = int(totals["open_count"] or 0)
        pnl_usd = float(totals["pnl_usd"] or 0.0)
        accuracy = (wins / resolved * 100.0) if resolved > 0 else 0.0

        by_category = []
        for r in by_category_rows:
            by_category.append(
                {
                    "category": r["category"] or "other",
                    "total": int(r["total"] or 0),
                    "wins": int(r["wins"] or 0),
                    "losses": int(r["losses"] or 0),
                    "pnl_usd": float(r["pnl_usd"] or 0.0),
                }
            )

        return {
            "total": total,
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "open": open_count,
            "accuracy_pct": round(accuracy, 1),
            "pnl_usd": round(pnl_usd, 2),
            "by_category": by_category,
        }
