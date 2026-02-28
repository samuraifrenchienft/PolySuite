"""Contrarian Long-Shot Alert - high volume one outcome, high payout on the other.

Strategy: Polymarket 'golden odds' 20-40% - when crowd piles on one side,
the minority side has high payout. Score = imbalance_ratio × payout.
"""

import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ContrarianDetector:
    """Detect contrarian opportunities: high volume one outcome, high payout on the other."""

    def __init__(
        self,
        polymarket_api=None,
        min_volume: float = 10000,
        min_imbalance: float = 0.6,
        payout_range: Tuple[float, float] = (0.20, 0.40),
        limit: int = 5,
    ):
        self.polymarket_api = polymarket_api
        self.min_volume = min_volume
        self.min_imbalance = min_imbalance  # e.g. 0.6 = 60% on one side
        self.payout_range = payout_range  # minority price 0.20-0.40 = 5x-2.5x
        self.limit = limit

    def scan(self) -> List[Dict]:
        """Scan for contrarian opportunities. Returns list of signal dicts."""
        signals = []
        if not self.polymarket_api or not hasattr(self.polymarket_api, "get_market_trades"):
            return signals

        try:
            markets = self.polymarket_api.get_active_markets(limit=80, order="volume")
            for m in markets:
                vol = float(m.get("volume", 0) or 0)
                if vol < self.min_volume:
                    continue

                mid = m.get("conditionId") or m.get("id")
                if not mid:
                    continue

                vol_yes, vol_no, payout_minority = self._aggregate_trades_by_outcome(mid, m)
                if vol_yes is None:
                    continue

                total = vol_yes + vol_no
                if total < 100:
                    continue

                # Majority side and its share
                if vol_yes >= vol_no:
                    majority_vol, minority_vol = vol_yes, vol_no
                    majority_side, minority_side = "YES", "NO"
                    # Minority price = NO price; outcomePrices[1] typically
                    prices = m.get("outcomePrices")
                    if isinstance(prices, str):
                        import json
                        try:
                            prices = json.loads(prices)
                        except Exception:
                            prices = [0.5, 0.5]
                    minority_price = float(prices[1]) if prices and len(prices) >= 2 else 0.5
                else:
                    majority_vol, minority_vol = vol_no, vol_yes
                    majority_side, minority_side = "NO", "YES"
                    prices = m.get("outcomePrices")
                    if isinstance(prices, str):
                        import json
                        try:
                            prices = json.loads(prices)
                        except Exception:
                            prices = [0.5, 0.5]
                    minority_price = float(prices[0]) if prices and len(prices) >= 2 else 0.5

                imbalance = majority_vol / total if total > 0 else 0
                if imbalance < self.min_imbalance:
                    continue

                # Payout = 1/price for binary (e.g. 0.25 -> 4x)
                payout = 1.0 / minority_price if minority_price > 0.01 else 0
                if not (self.payout_range[0] <= minority_price <= self.payout_range[1]):
                    continue

                score = imbalance * payout
                signals.append({
                    "market": m,
                    "market_id": mid,
                    "question": (m.get("question") or "Unknown")[:80],
                    "source": "polymarket",
                    "vol_yes": vol_yes,
                    "vol_no": vol_no,
                    "majority_side": majority_side,
                    "minority_side": minority_side,
                    "minority_price": minority_price,
                    "payout": payout,
                    "imbalance": imbalance,
                    "score": score,
                    "total_volume": total,
                })
                if len(signals) >= self.limit:
                    break

            signals.sort(key=lambda x: x["score"], reverse=True)
            return signals[: self.limit]

        except Exception as e:
            logger.warning("ContrarianDetector scan failed: %s", e)
        return signals

    def _aggregate_trades_by_outcome(
        self, market_id: str, market: Dict
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Aggregate trade volume by YES/NO. Returns (vol_yes, vol_no, payout_minority) or (None,None,None)."""
        try:
            trades = self.polymarket_api.get_market_trades(market_id, limit=200)
            vol_yes = 0.0
            vol_no = 0.0

            for t in trades or []:
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                usd = size * price
                if usd <= 0:
                    continue

                outcome = (t.get("outcome") or t.get("outcomeType") or "").upper()
                if "YES" in outcome or outcome == "Y":
                    vol_yes += usd
                elif "NO" in outcome or outcome == "N":
                    vol_no += usd
                else:
                    # Infer from price
                    if price >= 0.5:
                        vol_yes += usd
                    else:
                        vol_no += usd

            return (vol_yes, vol_no, None)
        except Exception as e:
            logger.debug("Contrarian trades for %s: %s", market_id[:16], e)
        return (None, None, None)
