"""Insider signal detection - new account + large trade + immediate win.

For copy traders: detect wallets that exhibit possible insider behavior
(fresh wallet, large trade, winning outcome) to follow early.

Phase B: Size anomaly vs order book, niche market flag, composite risk score.
"""

import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


def _parse_order_depth(levels: list, top_n: int = 5) -> float:
    """Sum USD value at top N order book levels."""
    if not levels:
        return 0.0
    total = 0.0
    for i, level in enumerate(levels[:top_n]):
        try:
            price = float(
                level.get("price", 0)
                if isinstance(level, dict)
                else getattr(level, "price", 0)
            )
            size = float(
                level.get("size", 0)
                if isinstance(level, dict)
                else getattr(level, "size", 0)
            )
            total += price * size
        except (ValueError, TypeError):
            pass
    return total


def _normalize_side(value: Any) -> str:
    """Normalize assorted outcome fields to YES/NO/UNKNOWN."""
    if value is None:
        return "UNKNOWN"
    s = str(value).strip().lower()
    if s in ("yes", "y", "true", "1"):
        return "YES"
    if s in ("no", "n", "false", "0"):
        return "NO"
    return "UNKNOWN"


class InsiderSignalDetector:
    """Detect possible insider signals: fresh wallet + large trade + winning outcome."""

    def __init__(
        self,
        hashdive_client=None,
        polymarket_api=None,
        insider_detector=None,
        api_factory=None,
        min_trade_usd: float = 5000,
        fresh_max_trades: int = 10,
        liquidity_threshold: float = 0.02,
        niche_volume_max: float = 50000,
    ):
        self.hashdive = (
            hashdive_client  # Optional paid; Polymarket Data API used when not set
        )
        self.polymarket = polymarket_api
        self.insider = insider_detector
        self.api_factory = api_factory
        self.min_trade_usd = min_trade_usd
        self.fresh_max_trades = fresh_max_trades
        self.liquidity_threshold = liquidity_threshold
        self.niche_volume_max = niche_volume_max

    def scan_for_signals(self, limit: int = 10) -> List[Dict]:
        """Scan for insider signals. Returns list of signal dicts."""
        signals = []
        seen_wallets = set()

        # Source 1: Large trades (Polymarket Data API free, or HashDive if configured)
        whale_client = self.hashdive
        if not whale_client or not hasattr(whale_client, "get_latest_whale_trades"):
            from src.market.polymarket_whale import PolymarketWhaleClient

            whale_client = PolymarketWhaleClient()
        try:
            trades = whale_client.get_latest_whale_trades(
                min_usd=int(self.min_trade_usd), limit=30
            )
            if trades:
                for t in trades:
                    addr = (t.get("address") or t.get("wallet") or "").strip()
                    if not addr or addr.lower() in seen_wallets:
                        continue
                    seen_wallets.add(addr.lower())
                    sig = self._check_wallet_signal(addr, t)
                    if sig:
                        signals.append(sig)
                        if len(signals) >= limit:
                            return signals
        except Exception as e:
            logger.warning("InsiderSignal whale trades scan failed: %s", e)

        # Source 2: Leaderboard (fallback when no large-trade signals)
        if not signals and self.polymarket:
            try:
                import requests

                resp = requests.get(
                    "https://data-api.polymarket.com/v1/leaderboard",
                    params={"category": "OVERALL", "limit": 30},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    wallets = data if isinstance(data, list) else []
                    for w in wallets[:15]:
                        addr = (w.get("proxyWallet") or w.get("address") or "").strip()
                        if not addr or addr.lower() in seen_wallets:
                            continue
                        seen_wallets.add(addr.lower())
                        sig = self._check_wallet_signal(addr, {"size": 0})
                        if sig:
                            signals.append(sig)
                            if len(signals) >= limit:
                                return signals
            except Exception as e:
                logger.warning("InsiderSignal leaderboard fallback failed: %s", e)

        return signals

    def _check_size_and_niche(self, market_id: str, trade_size: float) -> tuple:
        """Check size anomaly vs order book and niche market. Returns (size_anomaly, niche_market, liquidity_impact)."""
        size_anomaly = False
        niche_market = False
        liquidity_impact = None
        try:
            clob = (
                self.api_factory.get_clob_client()
                if hasattr(self.api_factory, "get_clob_client")
                else None
            )
            if not clob:
                return (False, False, None)
            market = clob.get_market(market_id)
            if not market:
                return (False, False, None)
            if isinstance(market, dict):
                pass
            elif hasattr(market, "__dict__"):
                market = vars(market)
            else:
                return (False, False, None)

            # Niche market: volume < threshold
            vol = float(market.get("volume", 0) or market.get("volumeNum", 0) or 0)
            niche_market = vol > 0 and vol < self.niche_volume_max

            # Size anomaly: trade_size / order_book_depth > threshold
            token_ids = market.get("clobTokenIds") or market.get("clob_token_ids")
            if not token_ids:
                return (size_anomaly, niche_market, liquidity_impact)
            token_id = (
                token_ids[0] if isinstance(token_ids, (list, tuple)) else token_ids
            )
            if not token_id:
                return (size_anomaly, niche_market, liquidity_impact)
            order_book = clob.get_order_book(token_id)
            if not order_book:
                return (size_anomaly, niche_market, liquidity_impact)
            bids = order_book.get("bids") or []
            asks = order_book.get("asks") or []
            bid_depth = _parse_order_depth(bids)
            ask_depth = _parse_order_depth(asks)
            depth = min(bid_depth, ask_depth)
            if depth > 0:
                liquidity_impact = trade_size / depth
                size_anomaly = liquidity_impact > self.liquidity_threshold
        except Exception as e:
            logger.debug(
                "InsiderSignal size/niche check %s: %s",
                market_id[:16] if market_id else "?",
                e,
            )
        return (size_anomaly, niche_market, liquidity_impact)

    def _check_wallet_signal(self, address: str, trade: Dict) -> Optional[Dict]:
        """Check if wallet exhibits insider signal. Returns signal dict or None."""
        if not self.insider or not self.polymarket:
            return None

        try:
            # Get closed positions to check freshness and winning
            import requests

            resp = requests.get(
                "https://data-api.polymarket.com/closed-positions",
                params={"user": address, "limit": 50},
                timeout=10,
            )
            closed = resp.json() if resp.status_code == 200 else []

            closed_count = len(closed)
            if closed_count >= self.fresh_max_trades:
                return None  # Not fresh

            # Check for winning trade
            has_win = False
            last_win = None
            winning_position = None
            for p in closed[:5]:
                pnl = p.get("realizedPnl") or p.get("pnl") or p.get("realized_pnl")
                try:
                    pnl_val = float(pnl) if pnl is not None else 0
                    if pnl_val > 0:
                        has_win = True
                        last_win = {
                            "question": (
                                p.get("question")
                                or p.get("marketQuestion")
                                or p.get("title")
                                or "Unknown"
                            )[:80],
                            "pnl": pnl_val,
                            "side": _normalize_side(
                                p.get("outcome")
                                or p.get("side")
                                or p.get("position")
                                or p.get("tokenOutcome")
                            ),
                            "market_id": p.get("conditionId")
                            or p.get("market")
                            or p.get("condition_id"),
                        }
                        break
                except (ValueError, TypeError):
                    pass

            if not has_win or not last_win:
                return None

            # Trade size from HashDive trade or estimate from closed
            trade_size = float(trade.get("size", 0) or trade.get("usdSize", 0) or 0)
            if trade_size < self.min_trade_usd and closed:
                # Estimate from closed position
                for p in closed[:3]:
                    size = float(
                        p.get("size", 0)
                        or p.get("usdcSize", 0)
                        or p.get("totalBought", 0)
                        or 0
                    )
                    if size >= self.min_trade_usd:
                        trade_size = size
                        break

            if trade_size < self.min_trade_usd:
                return None

            # Phase B: Size anomaly, niche market, composite score
            size_anomaly = False
            niche_market = False
            liquidity_impact = None
            if self.api_factory and last_win.get("market_id"):
                size_anomaly, niche_market, liquidity_impact = (
                    self._check_size_and_niche(last_win["market_id"], trade_size)
                )

            # Auto-HIGH for huge trades (> $100K) - regardless of order book
            if trade_size >= 100000:
                size_anomaly = True

            # Composite risk: fresh + size_anomaly + niche_market
            fresh = closed_count < self.fresh_max_trades
            signal_count = sum([fresh, size_anomaly, niche_market])
            if signal_count >= 3 or trade_size >= 100000:
                confidence = "HIGH"
            elif signal_count >= 2:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            return {
                "address": address,
                "trade_size": trade_size,
                "closed_count": closed_count,
                "winning_trade": last_win,
                "risk": "HIGH" if closed_count < 5 else "MEDIUM",
                "size_anomaly": size_anomaly,
                "niche_market": niche_market,
                "liquidity_impact": liquidity_impact,
                "confidence": confidence,
                "signals": {
                    "fresh": fresh,
                    "size_anomaly": size_anomaly,
                    "niche_market": niche_market,
                },
            }
        except Exception as e:
            logger.debug("InsiderSignal check %s: %s", address[:12], e)
            return None
