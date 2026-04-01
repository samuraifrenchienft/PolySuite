"""Binary market entry margin helpers for alert gating.

Standard (Polymarket YES/NO):
  - Implied price p in (0,1) = cost per $1 of payout if you win (simplified).
  - Profit per $ staked if outcome wins: (1 - p) / p.
  - As percent: stake_roi_if_win_pct = 100 * (1 - p) / p.

Examples:
  - p = 0.90 (heavy favorite) -> ~11.1% return on stake if win -> often too thin to alert on.
  - p = 0.50 -> 100% return on stake if win.
  - p = 0.20 -> 400% return on stake if win (contrarian long-shot band).

alert_min_entry_roi_pct (config) requires stake_roi_if_win_pct >= that value, i.e. skips
alerts where the consensus/outcome side is too expensive (low profit margin vs stake).

If price is missing, we do not block (avoid false negatives).
For convergence, if prices are present but side is ambiguous, we fail closed to avoid
bypassing the noise floor.
Set alert_min_entry_roi_pct to 0 to disable this filter.

Priority (HIGH/MEDIUM/LOW via assign_alert_priority) ranks signals *after* the noise floor.
It never weakens gates — only labels how strong the opportunity is among valid alerts.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def normalize_yes_no(side: Any) -> Optional[str]:
    """Normalize outcome/side strings to YES or NO."""
    if side is None:
        return None
    s = str(side).strip().lower()
    if s in ("yes", "y", "true", "1"):
        return "YES"
    if s in ("no", "n", "false", "0"):
        return "NO"
    # Handle mixed labels like "BUY YES", "Outcome: No", "yes_token".
    has_yes = bool(re.search(r"\byes\b", s))
    has_no = bool(re.search(r"\bno\b", s))
    if has_yes and not has_no:
        return "YES"
    if has_no and not has_yes:
        return "NO"
    return None


def parse_outcome_prices(market: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    """Return (yes_price, no_price) from Gamma/CLOB-style market dict, or None."""
    if not market:
        return None
    raw = market.get("outcomePrices") or market.get("outcome_prices")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        yes_p = float(raw[0])
        no_p = float(raw[1])
    except (TypeError, ValueError):
        return None
    if yes_p <= 0 or yes_p >= 1 or no_p <= 0 or no_p >= 1:
        return None
    return yes_p, no_p


def implied_price_for_side(side: str, yes_p: float, no_p: float) -> Optional[float]:
    """Price for YES or NO outcome."""
    s = (side or "").strip().upper()
    if s == "YES":
        return yes_p
    if s == "NO":
        return no_p
    return None


def stake_roi_if_win_pct(price: float) -> float:
    """Profit per $ staked if outcome wins, as a percent (binary market)."""
    if price <= 0 or price >= 1:
        return 0.0
    return (1.0 - price) / price * 100.0


def entry_meets_min_stake_roi(price: Optional[float], min_roi_pct: float) -> bool:
    """True if implied price offers at least min_roi_pct return-on-stake if win."""
    try:
        min_r = float(min_roi_pct)
    except (TypeError, ValueError):
        min_r = 0.0
    if min_r <= 0:
        return True
    if price is None:
        return True
    try:
        p = float(price)
    except (TypeError, ValueError):
        return True
    return stake_roi_if_win_pct(p) >= min_r - 1e-9


def price_for_side_from_market(market: Optional[Dict[str, Any]], side: Any) -> Optional[float]:
    """Resolve YES/NO token price from market + side."""
    norm = normalize_yes_no(side)
    if not norm:
        return None
    pr = parse_outcome_prices(market)
    if not pr:
        return None
    yes_p, no_p = pr
    return implied_price_for_side(norm, yes_p, no_p)


def majority_convergence_side(wallets: List[Dict[str, Any]]) -> Optional[str]:
    """Most common YES/NO among convergence wallet entries."""
    sides: List[str] = []
    for w in wallets:
        n = normalize_yes_no(w.get("side"))
        if n:
            sides.append(n)
    if not sides:
        return None
    return Counter(sides).most_common(1)[0][0]


def max_implied_price_for_min_roi(min_roi_pct: float) -> Optional[float]:
    """For min ROI r%, maximum price p such that (1-p)/p*100 >= r: p <= 100/(100+r)."""
    try:
        r = float(min_roi_pct)
    except (TypeError, ValueError):
        return None
    if r <= 0:
        return None
    return 100.0 / (100.0 + r)


def convergence_passes_entry_roi(
    conv: Dict[str, Any],
    min_roi_pct: float,
) -> bool:
    """True if consensus side in convergence meets min stake ROI vs current odds."""
    try:
        min_r = float(min_roi_pct)
    except (TypeError, ValueError):
        min_r = 0.0
    if min_r <= 0:
        return True
    market = conv.get("market_info") or {}
    prices = parse_outcome_prices(market)
    wallets = conv.get("wallets") or []
    side = majority_convergence_side(wallets)
    if not side:
        # Fail closed when we do have price data but cannot infer side: avoid bypassing
        # the noise floor with ambiguous convergence direction.
        return prices is None
    p = price_for_side_from_market(market, side)
    if p is None and prices is not None:
        return False
    ok = entry_meets_min_stake_roi(p, min_r)
    if not ok and p is not None:
        logger.debug(
            "Convergence skipped (low entry margin): side=%s price=%.4f roi_if_win=%.1f%% min=%.1f%%",
            side,
            p,
            stake_roi_if_win_pct(p),
            min_r,
        )
    return ok


def insider_winning_trade_passes_entry_roi(
    signal: Dict[str, Any],
    polymarket_api: Any,
    min_roi_pct: float,
    market_cache: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
) -> bool:
    """True if current odds for the winning-trade side meet min stake ROI (copy/follow value)."""
    try:
        min_r = float(min_roi_pct)
    except (TypeError, ValueError):
        min_r = 0.0
    if min_r <= 0:
        return True
    market, market_id, side = _get_insider_market_context(signal, polymarket_api, market_cache)
    if not market_id or not polymarket_api:
        return True
    if market is None:
        return True
    p = price_for_side_from_market(market, side)
    ok = entry_meets_min_stake_roi(p, min_r)
    if not ok and p is not None:
        logger.debug(
            "Insider skipped (low entry margin): price=%.4f roi_if_win=%.1f%% min=%.1f%%",
            p,
            stake_roi_if_win_pct(p),
            min_r,
        )
    return ok


def insider_winning_trade_stake_roi_pct(
    signal: Dict[str, Any],
    polymarket_api: Any,
    market_cache: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
) -> Optional[float]:
    """Stake ROI % if win for insider winning_trade side at current market price."""
    market, market_id, side = _get_insider_market_context(signal, polymarket_api, market_cache)
    if not market_id or not polymarket_api:
        return None
    if market is None:
        return None
    p = price_for_side_from_market(market, side)
    if p is None:
        return None
    return stake_roi_if_win_pct(p)


def convergence_stake_roi_pct(conv: Dict[str, Any]) -> Optional[float]:
    """Stake ROI % if win for majority convergence side at current market price."""
    market = conv.get("market_info") or {}
    wallets = conv.get("wallets") or []
    side = majority_convergence_side(wallets)
    if not side:
        return None
    p = price_for_side_from_market(market, side)
    if p is None:
        return None
    return stake_roi_if_win_pct(p)


def priority_tier_from_roi(
    stake_roi_pct: Optional[float],
    high_min: float,
    medium_min: float,
) -> str:
    """Label attention tier from stake ROI alone (after noise floor)."""
    if stake_roi_pct is None:
        return "MEDIUM"
    if stake_roi_pct >= high_min:
        return "HIGH"
    if stake_roi_pct >= medium_min:
        return "MEDIUM"
    return "LOW"


def assign_alert_priority(
    *,
    stake_roi_pct: Optional[float],
    config: Any,
    insider_signal: Optional[Dict[str, Any]] = None,
    convergence: Optional[Dict[str, Any]] = None,
) -> str:
    """Rank signal AFTER noise gates (min entry ROI, confidence, etc.).

    HIGH/MEDIUM/LOW is for attention and formatting only — it does not relax any
    filters. Anything that alerts has already passed the noise floor.
    """
    enabled = bool(_config_get(config, "alert_priority_enabled", True))
    if not enabled:
        return "MEDIUM"

    high_m = float(_config_get(config, "alert_priority_high_min_roi_pct", 25) or 25)
    med_m = float(_config_get(config, "alert_priority_medium_min_roi_pct", 15) or 15)
    tier = priority_tier_from_roi(stake_roi_pct, high_m, med_m)

    # Convergence: structural strength (only boosts tier among already-valid alerts)
    if convergence:
        w = len(convergence.get("wallets") or [])
        early = bool(convergence.get("has_early_entry"))
        if early and w >= 4:
            tier = "HIGH"
        elif early and w >= 3 and tier == "LOW":
            tier = "MEDIUM"

    # Insider: strong detector confidence + book impact
    if insider_signal and bool(_config_get(config, "alert_priority_insider_bump", True)):
        conf = (insider_signal.get("confidence") or "").upper()
        if conf == "HIGH" and insider_signal.get("size_anomaly"):
            tier = "HIGH"
        elif conf == "HIGH" and tier == "LOW":
            tier = "MEDIUM"

    return tier


def _config_get(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    get = getattr(config, "get", None)
    if callable(get):
        return get(key, default)
    return default


def _get_insider_market_context(
    signal: Dict[str, Any],
    polymarket_api: Any,
    market_cache: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Any]:
    """Return (market, market_id, side) for insider winning_trade, with optional cache."""
    wt = signal.get("winning_trade") or {}
    market_id = wt.get("market_id")
    side = wt.get("side")
    if not market_id or not polymarket_api:
        return None, market_id, side

    if market_cache is not None and market_id in market_cache:
        return market_cache.get(market_id), market_id, side

    try:
        market = polymarket_api.get_market(market_id)
    except Exception as e:
        logger.debug("Insider market fetch failed %s: %s", str(market_id)[:16], e)
        market = None

    if market_cache is not None:
        market_cache[market_id] = market
    return market, market_id, side
