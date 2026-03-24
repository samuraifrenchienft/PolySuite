"""Shared Polymarket trade resolution stats (aligned with WalletVetting logic).

Used by WalletCalculator and optional tooling so dashboard win rate matches vet/classify
instead of the old price heuristic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _has_closed_position(api, address: str, market_id: str) -> bool:
    """True if no open position on this market (vetting semantics)."""
    try:
        positions = api.get_wallet_positions(address) if api else []
    except Exception as e:
        logger.debug("resolution_stats positions: %s", e)
        return True
    for pos in positions or []:
        mid = pos.get("conditionId") or pos.get("market")
        if mid == market_id:
            return False
    return True


@dataclass
class PolymarketResolutionRollup:
    total_trades: int
    total_volume: float
    resolved_wins: int
    resolved_decisions: int  # trades counted as win or loss on a resolved market
    winning_trade_notional: float  # USD sum of trades counted as wins (fee proxy)


def compute_polymarket_resolution_rollup(
    api,
    address: str,
    trades: List[Dict[str, Any]],
    max_markets: int = 120,
    market_cache: Optional[Dict[str, Any]] = None,
) -> PolymarketResolutionRollup:
    """Resolve markets (capped) and count wins the same way as vetting.

    Args:
        api: Polymarket API client (get_market, get_wallet_positions).
        address: Wallet (for open-position check on unresolved BUY losses).
        trades: Raw trade dicts from get_wallet_trades.
        max_markets: Max unique conditionIds to fetch (rest skipped for volume only).
        market_cache: Optional shared cache condition_id -> market dict (mutated).
    """
    if not trades:
        return PolymarketResolutionRollup(0, 0.0, 0, 0, 0.0)

    cache = market_cache if market_cache is not None else {}
    trade_market_map: List[Tuple[Dict[str, Any], str]] = []
    market_ids: List[str] = []
    seen: set = set()
    for trade in trades:
        mid = trade.get("conditionId") or trade.get("market")
        if not mid:
            continue
        trade_market_map.append((trade, mid))
        if mid not in seen:
            seen.add(mid)
            market_ids.append(mid)

    # Prioritize markets with the most trades
    counts: Dict[str, int] = {}
    for _, m in trade_market_map:
        counts[m] = counts.get(m, 0) + 1
    market_ids.sort(key=lambda m: counts.get(m, 0), reverse=True)
    to_fetch = market_ids[: max(0, int(max_markets or 120))]

    for mid in to_fetch:
        if mid not in cache:
            try:
                cache[mid] = api.get_market(mid) if api else None
            except Exception as e:
                logger.debug("get_market %s: %s", mid[:12] if mid else "", e)
                cache[mid] = None

    resolved_wins = 0
    resolved_decisions = 0
    total_volume = 0.0
    winning_notional = 0.0

    for trade, market_id in trade_market_map:
        size = float(trade.get("size", 0) or 0)
        price = float(trade.get("price", 0) or 0)
        usd = float(
            trade.get("usdcSize")
            or trade.get("usdAmount")
            or trade.get("usdc_amount")
            or 0
        )
        if usd <= 0 and size and price:
            usd = abs(size * price)
        total_volume += usd

        market = cache.get(market_id)
        if not market:
            continue

        resolved = market.get("resolved") or market.get("closed")
        if not resolved:
            continue

        winning_outcome = (market.get("outcome") or "").lower()
        if not winning_outcome:
            continue

        side = (trade.get("side", "") or "BUY").upper()
        trade_outcome = (
            trade.get("outcome") or trade.get("outcomeType") or ""
        ).lower()
        if not trade_outcome:
            trade_outcome = "no" if price < 0.5 else "yes"

        is_win = False
        is_loss = False
        if trade_outcome == winning_outcome and side == "BUY":
            resolved_wins += 1
            is_win = True
        elif trade_outcome != winning_outcome and side == "SELL":
            resolved_wins += 1
            is_win = True
        elif trade_outcome != winning_outcome and side == "BUY":
            if not _has_closed_position(api, address, market_id):
                pass  # unresolved loss — still a loss for decision count
            is_loss = True
        elif trade_outcome == winning_outcome and side == "SELL":
            is_loss = True

        if is_win or is_loss:
            resolved_decisions += 1
            if is_win:
                winning_notional += usd

    return PolymarketResolutionRollup(
        total_trades=len(trades),
        total_volume=total_volume,
        resolved_wins=resolved_wins,
        resolved_decisions=resolved_decisions,
        winning_trade_notional=winning_notional,
    )
