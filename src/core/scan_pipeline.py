"""Unified scan pipeline for strategy detectors.

Runs convergence, insider, contrarian scans and returns normalized results.
Shared by collector and dashboard to reduce duplication.
Optionally persists results for analytics.
"""

import time
from typing import Any, Dict, List, Optional

from src.core.detector_factory import DetectorFactory


class ScanPipeline:
    """Run strategy scans and return normalized results."""

    def __init__(
        self,
        factory: DetectorFactory,
        scan_results_storage=None,
    ):
        self.factory = factory
        self.scan_results_storage = scan_results_storage

    def run_convergence(self, min_wallets: int = 2) -> Dict[str, Any]:
        """Run convergence scan."""
        try:
            detector = self.factory.get_convergence_detector()
            convergences = detector.find_convergences(min_wallets=min_wallets)
            out = []
            for c in convergences:
                m = c.get("market_info") or {}
                out.append({
                    "market_id": c.get("market_id"),
                    "question": (m.get("question") or "Unknown")[:120],
                    "wallet_count": c.get("wallet_count", 0),
                    "has_early_entry": c.get("has_early_entry", False),
                    "market_age_hours": c.get("market_age_hours"),
                    "wallets": [
                        {"address": w.get("address"), "nickname": w.get("nickname"), "win_rate": w.get("win_rate"), "side": w.get("side")}
                        for w in c.get("wallets", [])
                    ],
                    "link": f"https://polymarket.com/market/{c.get('market_id', '')}" if c.get("market_id") else "",
                })
            result = {"ok": True, "convergences": out, "count": len(out), "ts": time.time()}
            if self.scan_results_storage:
                self.scan_results_storage.save("convergence", result["ts"], len(out), result)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "convergences": [], "count": 0, "ts": time.time()}

    def run_insider(self, limit: int = 10, apply_noise_filters: bool = False) -> Dict[str, Any]:
        """Run insider scan. Set apply_noise_filters=True for alert use (collector)."""
        try:
            detector = self.factory.get_insider_detector()
            signals = detector.scan_for_signals(limit=limit)
            min_pnl = float(self.factory._get("alert_min_pnl", 500) or 500)
            skip_low = self.factory._get("alert_skip_low_confidence", True)

            out = []
            for s in signals:
                wt = s.get("winning_trade") or {}
                if apply_noise_filters:
                    if skip_low and (s.get("confidence") or "LOW").upper() == "LOW":
                        continue
                    if float(wt.get("pnl", 0) or 0) < min_pnl:
                        continue
                out.append({
                    "address": s.get("address", ""),
                    "trade_size": round(s.get("trade_size", 0), 0),
                    "closed_count": s.get("closed_count", 0),
                    "confidence": s.get("confidence", "LOW"),
                    "question": (wt.get("question") or "Unknown")[:100],
                    "pnl": round(wt.get("pnl", 0), 2),
                    "side": wt.get("side", "?"),
                    "size_anomaly": s.get("size_anomaly", False),
                    "niche_market": s.get("niche_market", False),
                    "link": f"https://polymarket.com/profile/{s.get('address', '')}" if s.get("address") else "",
                })
            result = {"ok": True, "signals": out, "count": len(out), "ts": time.time()}
            if self.scan_results_storage:
                self.scan_results_storage.save("insider", result["ts"], len(out), result)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "signals": [], "count": 0, "ts": time.time()}

    def run_contrarian(self) -> Dict[str, Any]:
        """Run contrarian scan."""
        try:
            detector = self.factory.get_contrarian_detector()
            signals = detector.scan()
            out = []
            for s in signals:
                out.append({
                    "market_id": s.get("market_id"),
                    "question": (s.get("question") or "Unknown")[:120],
                    "vol_yes": s.get("vol_yes", 0),
                    "vol_no": s.get("vol_no", 0),
                    "majority_side": s.get("majority_side"),
                    "minority_side": s.get("minority_side"),
                    "minority_price": round(s.get("minority_price", 0), 2),
                    "payout": round(s.get("payout", 0), 1),
                    "imbalance": round(s.get("imbalance", 0), 2),
                    "score": round(s.get("score", 0), 2),
                    "total_volume": s.get("total_volume", 0),
                    "link": f"https://polymarket.com/market/{s.get('market_id', '')}" if s.get("market_id") else "",
                })
            result = {"ok": True, "signals": out, "count": len(out), "ts": time.time()}
            if self.scan_results_storage:
                self.scan_results_storage.save("contrarian", result["ts"], len(out), result)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "signals": [], "count": 0, "ts": time.time()}
