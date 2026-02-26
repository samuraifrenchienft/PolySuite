"""Multi-layer qualification for Zigma-style alert filtering.

Markets must pass all gates to be alerted. Reject if any criterion fails.
"""

from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta


def _parse_end_date(end_date_str: Optional[str]) -> Optional[datetime]:
    """Parse end_date to datetime. Returns None if invalid."""
    if not end_date_str:
        return None
    try:
        if "T" in str(end_date_str):
            dt = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(str(end_date_str)[:10], "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def check_execution_traps(
    market: dict,
    order_book: Optional[Dict] = None,
    spread_pct: float = 0,
    min_depth_usd: float = 2000,
) -> Dict[str, Any]:
    """Check for execution traps: thin book, headline risk.

    Returns:
        dict with pass (bool), traps (list of detected trap names)
    """
    result = {"pass": True, "traps": []}

    if order_book:
        bids = order_book.get("bids") or []
        asks = order_book.get("asks") or []
        bid_depth = sum(
            float(b.get("price", 0) or 0) * float(b.get("size", 0) or 0)
            for b in bids[:3]
        )
        ask_depth = sum(
            float(a.get("price", 0) or 0) * float(a.get("size", 0) or 0)
            for a in asks[:3]
        )
        depth = min(bid_depth, ask_depth)
        if depth < min_depth_usd:
            result["pass"] = False
            result["traps"].append("thin_book")

    headline_keywords = ["breaking", "just in", "developing", "live:", "urgent"]
    question = (market.get("question") or market.get("title") or "").lower()
    if any(kw in question for kw in headline_keywords):
        result["pass"] = False
        result["traps"].append("headline_risk")

    return result


class Qualifier:
    """Multi-layer qualification for alerts."""

    def __init__(
        self,
        min_volume: float = 5000,
        min_expiring_hours: float = 1.0,
        strict_mode: bool = False,
    ):
        self.min_volume = min_volume
        self.min_expiring_hours = min_expiring_hours
        self.strict_mode = strict_mode

    def qualify_new_market(
        self,
        market: dict,
        ai_analysis: Optional[Dict] = None,
        liquidity_result: Optional[Dict] = None,
        arb_profit: float = 0,
        require_liquidity: bool = False,
    ) -> Tuple[bool, str]:
        """Qualify a new market. Returns (pass, rejection_reason).

        Gates (all must pass):
        - Volume >= min_volume
        - AI opportunity: not (LOW and volume < 5k) when strict
        - Liquidity: pass when require_liquidity and liquidity_result provided
        - Time decay: not expiring in < min_expiring_hours
        """
        ai_analysis = ai_analysis or {}
        volume = float(market.get("volume", 0) or 0)

        if volume < self.min_volume:
            return False, f"volume < {self.min_volume}"

        if self.strict_mode:
            opp = ai_analysis.get("opportunity", "")
            if opp == "LOW" and volume < 5000 and arb_profit < 0.5:
                return False, "AI opportunity LOW and volume < 5k"

        if require_liquidity and liquidity_result is not None:
            if not liquidity_result.get("pass", True):
                return False, "liquidity check failed"

        traps_result = check_execution_traps(
            market,
            order_book=liquidity_result.get("order_book") if liquidity_result else None,
            spread_pct=liquidity_result.get("spread_pct", 0) if liquidity_result else 0,
        )
        if not traps_result.get("pass", True):
            return False, f"execution traps: {', '.join(traps_result.get('traps', []))}"

        end_date = _parse_end_date(
            market.get("endDate") or market.get("end_date")
        )
        if end_date:
            now = datetime.now(timezone.utc)
            hours_left = (end_date - now).total_seconds() / 3600
            if hours_left < self.min_expiring_hours and hours_left > 0:
                return False, f"expiring in < {self.min_expiring_hours}h"

        return True, ""

    def qualify_arb(
        self,
        arb: dict,
        ai_analysis: Optional[Dict] = None,
    ) -> Tuple[bool, str]:
        """Qualify an arbitrage opportunity."""
        ai_analysis = ai_analysis or {}
        profit = float(arb.get("profit_pct", 0) or 0)
        volume = float(arb.get("volume", 0) or 0)

        if profit < 0.3:
            return False, "profit too small"

        if volume < 1000 and profit < 1.0:
            return False, "low volume and profit"

        return True, ""

    def qualify_convergence(
        self,
        conv: dict,
        market: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Qualify a convergence alert."""
        wallets = conv.get("wallets", [])
        if len(wallets) < 2:
            return False, "fewer than 2 wallets"

        return True, ""
