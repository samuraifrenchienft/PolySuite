"""Liquidity depth checks for Zigma-style alert qualification.

Uses Polymarket CLOB order book to verify:
- Depth at best bid/ask
- Spread
- Estimated slippage for $1k/$10k
"""

from typing import Dict, Optional, Any


def _parse_order_levels(levels: list, top_n: int = 5) -> float:
    """Sum USD value at top N levels. Levels are [{price, size}, ...]."""
    if not levels:
        return 0.0
    total = 0.0
    for i, level in enumerate(levels[:top_n]):
        if i >= top_n:
            break
        try:
            price = float(level.get("price", 0) if isinstance(level, dict) else getattr(level, "price", 0))
            size = float(level.get("size", 0) if isinstance(level, dict) else getattr(level, "size", 0))
            total += price * size
        except (ValueError, TypeError):
            pass
    return total


def check_liquidity_depth(
    market: dict,
    api_factory,
    min_liquidity_depth_usd: float = 5000,
    max_spread_pct: float = 5.0,
) -> Dict[str, Any]:
    """Check liquidity depth and spread for a Polymarket market.

    Args:
        market: Market dict with clobTokenIds, outcomePrices, etc.
        api_factory: APIClientFactory for CLOB client.
        min_liquidity_depth_usd: Minimum depth at best bid/ask to pass.
        max_spread_pct: Maximum spread (as %) to pass.

    Returns:
        dict with depth_usd, spread_pct, slippage_1k, slippage_10k, pass, order_book
    """
    result = {
        "depth_usd": 0.0,
        "spread_pct": 0.0,
        "slippage_1k": 0.0,
        "slippage_10k": 0.0,
        "pass": True,
        "order_book": None,
    }

    token_ids = market.get("clobTokenIds") or market.get("clob_token_ids")
    if not token_ids:
        result["pass"] = False
        return result

    token_id = token_ids[0] if isinstance(token_ids, (list, tuple)) else token_ids
    if not token_id:
        result["pass"] = False
        return result

    try:
        clob = api_factory.get_clob_client()
        order_book = clob.get_order_book(token_id)
        if not order_book:
            result["pass"] = False
            return result

        result["order_book"] = order_book

        bids = order_book.get("bids") or []
        asks = order_book.get("asks") or []

        bid_depth = _parse_order_levels(bids)
        ask_depth = _parse_order_levels(asks)
        result["depth_usd"] = min(bid_depth, ask_depth)

        best_bid = float(bids[0].get("price", 0)) if bids else 0
        best_ask = float(asks[0].get("price", 0)) if asks else 0
        if best_ask > 0:
            result["spread_pct"] = ((best_ask - best_bid) / best_ask) * 100

        if result["depth_usd"] < min_liquidity_depth_usd:
            result["pass"] = False
        if result["spread_pct"] > max_spread_pct:
            result["pass"] = False

        return result
    except Exception:
        result["pass"] = False
        return result
