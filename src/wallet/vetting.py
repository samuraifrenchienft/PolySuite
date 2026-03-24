"""Advanced wallet vetting for PolySuite - filters bots and P&L cheaters.

Fee-based filtering: Polymarket charges 2% only on winning bets, so estimated_fees_paid
proxies for winning volume. Kalshi: /portfolio/fills returns fee_cost but requires auth
(your account only); no public endpoint for other users' fees.
"""

import bisect
import logging
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from src.market.api import APIClientFactory, extract_market_category
from src.config import Config

logger = logging.getLogger(__name__)


class WalletVetting:
    """Vet wallets to filter out bots and P&L cheaters."""

    def __init__(self, api_factory: APIClientFactory, config: Optional[Config] = None):
        self.api_factory = api_factory
        self.api = api_factory.get_polymarket_api()
        self._jupiter_api = None
        self._config = config

    @property
    def jupiter_api(self):
        if self._jupiter_api is None:
            self._jupiter_api = self.api_factory.get_jupiter_prediction_client()
        return self._jupiter_api

    def _get_api(self, platform: str):
        """Get appropriate API client based on platform."""
        if platform == "jupiter":
            return self.jupiter_api
        return self.api

    def vet_wallet(
        self,
        address: str,
        min_bet: float = 10,
        platform: str = "polymarket",
        market_cache: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Fully vet a wallet and filter out bots and P&L cheaters.

        Polymarket: sequential flow - specialty/recent-wins merge, then fee gate.
        Kalshi/Jupiter: bypass fee gate (no fee data available).

        Args:
            address: Wallet address
            min_bet: Minimum average bet size to qualify
            platform: "polymarket" (default), "kalshi", or "jupiter" - fee gate only for polymarket

        Returns:
            Dict with vetting results or None if failed
        """
        api = self._get_api(platform)
        trades = api.get_wallet_trades(address, limit=500)
        if not trades:
            return None

        analysis = {
            "address": address,
            "total_trades": len(trades),
            "avg_bet_size": 0,
            "bot_score": 0,
            "unsettled_loses": 0,
            "resolved_markets_traded": 0,
            "win_rate_real": 0,
            "is_human": True,
            "is_settled": True,
            "passed": False,
            "issues": [],
            "total_pnl": 0,
            "roi_pct": 0,
            "conviction_score": 0,
            "trades_per_day": 0,
            "max_position_pct": 0,
            "recent_wins": 0,
            "recent_win_rate": 0.0,
            "current_win_streak": 0,
            "max_win_streak": 0,
            "win_rate_base": 0.0,
            "win_rate_trend": 0.0,
            "reliability_score": 0.0,
            "is_specialty": False,
            "specialty_note": None,
            "specialty_market_id": None,
            "specialty_category": None,
            "estimated_fees_paid": 0,
            "specialty_or_hot_streak_note": None,
            "total_wins": 0,
            "total_losses": 0,
            "top_category": None,
        }

        total_volume = 0
        category_volume = {}  # category -> volume for top_category
        wins = 0
        winning_trade_usd = 0.0  # fee proxy: Polymarket ~2% on winning settlements
        resolved_decisions = 0
        unresolved_losses = 0
        resolved_markets = set()
        resolved_trades_by_time = []  # (timestamp, market_id, is_win) for recent wins
        market_stats = {}  # market_id -> {"wins": int, "losses": int, "trades": [(ts, is_win), ...]}

        # N+1 fix: collect unique market_ids, fetch once per id
        market_ids = set()
        trade_market_map = []
        for trade in trades:
            mid = trade.get("conditionId") or trade.get("market")
            if mid:
                market_ids.add(mid)
                trade_market_map.append((trade, mid))

        if market_cache is None:
            market_cache = {}
        missing_ids = [mid for mid in market_ids if mid not in market_cache]
        if missing_ids:
            def _fetch_market(mid):
                try:
                    return self.api.get_market(mid)
                except Exception:
                    return None
            with ThreadPoolExecutor(max_workers=min(10, len(missing_ids))) as pool:
                fetched = pool.map(_fetch_market, missing_ids)
            for mid, data in zip(missing_ids, fetched):
                market_cache[mid] = data

        config = self._config or Config()
        max_unresolved = int(config.get("vet_max_unresolved_losses", 0) or 0)
        unresolved_min_days = int(config.get("vet_unresolved_min_days_past", 3) or 3)
        _positions_cache = None  # fetched at most once per vet when unresolved gate is active

        for trade, market_id in trade_market_map:
            size = float(trade.get("size", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            side = trade.get("side", "").upper()
            usd = size * price
            total_volume += usd

            market = market_cache.get(market_id)
            if market:
                cat = extract_market_category(market) or (
                    (market.get("category") or "other").lower()
                )
                category_volume[cat] = category_volume.get(cat, 0) + usd
            if market:
                resolved = market.get("resolved") or market.get("closed")
                if resolved:
                    resolved_markets.add(market_id)

                    raw_win = (market.get("outcome") or "").strip().lower()
                    winning_outcome = self._normalize_outcome(raw_win) if raw_win else raw_win
                    if winning_outcome:
                        # Resolve trade outcome: asset_id->token, else outcome/outcomeType, else price
                        trade_outcome = self._resolve_trade_outcome(trade, market, price)
                        # Win: bought winning side, or sold losing side before resolution
                        # Loss: bought losing side, or sold winning side (gave up the win)
                        is_win = False
                        is_loss = False
                        if trade_outcome == winning_outcome and side == "BUY":
                            wins += 1
                            is_win = True
                            winning_trade_usd += usd
                        elif trade_outcome != winning_outcome and side == "SELL":
                            wins += 1
                            is_win = True
                            winning_trade_usd += usd
                        elif trade_outcome != winning_outcome and side == "BUY":
                            # Unresolved: only when gate enabled (vet_max_unresolved_losses>0) +
                            # endDate days past + wallet still holds position (can't reliably track)
                            if max_unresolved > 0:
                                days_past = self._market_days_past_resolution(market)
                                if days_past >= unresolved_min_days:
                                    if _positions_cache is None:
                                        try:
                                            _positions_cache = self.api.get_wallet_positions(address) if self.api else []
                                        except Exception:
                                            _positions_cache = []
                                    if not self._has_closed_position_from_cache(_positions_cache, market_id):
                                        unresolved_losses += 1
                            is_loss = True
                        elif trade_outcome == winning_outcome and side == "SELL":
                            # Sold winning position before resolution - loss (not counted as win)
                            is_loss = True

                        # Collect for recent wins and per-market specialty
                        ts = (
                            trade.get("timestamp")
                            or trade.get("matchTime")
                            or trade.get("match_time")
                            or trade.get("createdAt")
                        )
                        trade_ts = None
                        if ts:
                            try:
                                if isinstance(ts, (int, float)):
                                    trade_ts = datetime.fromtimestamp(float(ts))
                                else:
                                    trade_ts = datetime.fromisoformat(
                                        str(ts).replace("Z", "+00:00")
                                    )
                            except (ValueError, TypeError):
                                pass
                        if trade_ts and (is_win or is_loss):
                            resolved_decisions += 1
                            resolved_trades_by_time.append(
                                (trade_ts, market_id, is_win)
                            )
                            if market_id not in market_stats:
                                market_stats[market_id] = {
                                    "wins": 0,
                                    "losses": 0,
                                    "trades": [],
                                }
                            market_stats[market_id]["trades"].append((trade_ts, is_win))
                            if is_win:
                                market_stats[market_id]["wins"] += 1
                            else:
                                market_stats[market_id]["losses"] += 1

        analysis["total_volume"] = total_volume
        analysis["avg_bet_size"] = total_volume / len(trades) if trades else 0
        analysis["top_category"] = (
            max(category_volume, key=category_volume.get) if category_volume else None
        )
        analysis["resolved_markets_traded"] = len(resolved_markets)

        if resolved_decisions > 0:
            analysis["win_rate_real"] = (wins / resolved_decisions) * 100

        analysis["unsettled_loses"] = unresolved_losses
        analysis["bot_score"] = self._calculate_bot_score(trades)

        # Smart money metrics
        total_pnl = 0
        estimated_fees = 0.0
        fee_from_closed = 0.0
        # Only get closed positions for Polymarket (Jupiter doesn't have this endpoint)
        if platform == "polymarket":
            try:
                closed = self.api.get_closed_positions(address, limit=100)
                for pos in closed or []:
                    pnl = pos.get("realizedPnl") or pos.get("realized_pnl")
                    if pnl is not None:
                        p = float(pnl)
                        total_pnl += p
                        if p > 0:
                            # ~2% fee on positive realized PnL (proxy; actual fee model varies)
                            fee_from_closed += p * 0.02
            except Exception as e:
                logger.debug("Vetting get_closed_positions error: %s", e)
        analysis["total_pnl"] = total_pnl
        # Trade-based proxy when closed-positions API is empty or lagging
        fee_from_wins = winning_trade_usd * 0.02
        estimated_fees = max(fee_from_closed, fee_from_wins)
        analysis["estimated_fees_paid"] = round(estimated_fees, 2)

        roi_pct = (total_pnl / total_volume * 100) if total_volume > 0 else 0
        analysis["roi_pct"] = roi_pct

        # Conviction: percentile of size*price per trade; avg of top 3
        trade_sizes = []
        market_volumes = {}
        trade_times = []
        for trade, market_id in trade_market_map:
            size = float(trade.get("size", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            usd = size * price
            trade_sizes.append(usd)
            market_volumes[market_id] = market_volumes.get(market_id, 0) + usd
            ts = (
                trade.get("timestamp")
                or trade.get("matchTime")
                or trade.get("match_time")
                or trade.get("createdAt")
            )
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        trade_times.append(datetime.fromtimestamp(float(ts)))
                    else:
                        trade_times.append(
                            datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        )
                except (ValueError, TypeError):
                    pass
        if trade_sizes:
            sorted_sizes = sorted(trade_sizes)
            n = len(sorted_sizes)
            percentiles = [
                (bisect.bisect_left(sorted_sizes, s) / n * 100) if s > 0 else 0
                for s in trade_sizes
            ]
            top3 = sorted(enumerate(percentiles), key=lambda x: x[1], reverse=True)[:3]
            conviction_score = sum(p for _, p in top3) / len(top3) if top3 else 0
        else:
            conviction_score = 0
        analysis["conviction_score"] = round(conviction_score, 1)

        days_span = 1
        if len(trade_times) >= 2:
            min_ts = min(trade_times)
            max_ts = max(trade_times)
            delta = (max_ts - min_ts).total_seconds()
            days_span = max(1, delta / 86400)
        analysis["trades_per_day"] = round(len(trades) / days_span, 1)

        max_market_vol = max(market_volumes.values()) if market_volumes else 0
        max_position_pct = (
            (max_market_vol / total_volume * 100) if total_volume > 0 else 0
        )
        analysis["max_position_pct"] = round(max_position_pct, 1)

        # Recent wins: count wins in last N resolved trades (by time)
        config = self._config or Config()
        resolved_trades_by_time.sort(key=lambda x: x[0])
        window = config.vet_recent_wins_window
        last_n = (
            resolved_trades_by_time[-window:]
            if len(resolved_trades_by_time) > window
            else resolved_trades_by_time
        )
        recent_wins = sum(1 for _, _, w in last_n if w)
        analysis["recent_wins"] = recent_wins
        analysis["recent_win_rate"] = (
            (recent_wins / len(last_n) * 100) if len(last_n) > 0 else 0.0
        )

        # Win streak metrics and gradual trend (older half -> recent half)
        if resolved_trades_by_time:
            ordered = sorted(resolved_trades_by_time, key=lambda x: x[0])
            outcomes = [w for _, _, w in ordered]

            streak = 0
            max_streak = 0
            for is_win in outcomes:
                if is_win:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 0

            current_streak = 0
            for is_win in reversed(outcomes):
                if is_win:
                    current_streak += 1
                else:
                    break

            analysis["current_win_streak"] = current_streak
            analysis["max_win_streak"] = max_streak
            analysis["is_win_streak_badge"] = max_streak >= config.win_streak_badge_threshold

            split = len(outcomes) // 2
            if split >= 2 and len(outcomes) - split >= 2:
                base_slice = outcomes[:split]
                recent_slice = outcomes[split:]
                base_rate = sum(1 for x in base_slice if x) / len(base_slice) * 100
                recent_rate = (
                    sum(1 for x in recent_slice if x) / len(recent_slice) * 100
                )
                analysis["win_rate_base"] = base_rate
                analysis["win_rate_trend"] = recent_rate - base_rate

        # Total wins/losses from resolved markets
        analysis["total_wins"] = wins
        analysis["total_losses"] = sum(s["losses"] for s in market_stats.values())

        # Win streak badge (separate from Specialist)
        if "is_win_streak_badge" not in analysis:
            analysis["is_win_streak_badge"] = analysis.get("max_win_streak", 0) >= config.win_streak_badge_threshold

        # Specialty: category focus + config-driven gates
        window_days = config.vet_specialty_window_days
        cutoff = datetime.utcnow() - timedelta(days=window_days)
        category_stats = {}  # category -> {wins, losses, trades}
        total_all_window_trades = 0
        for mid, stats in market_stats.items():
            cat = "other"
            m = market_cache.get(mid)
            if m:
                cat = (
                    extract_market_category(m)
                    or (m.get("category") or "other").lower().strip()
                    or "other"
                )
            if cat not in category_stats:
                category_stats[cat] = {"wins": 0, "losses": 0, "trades": 0}
            for trade_ts, is_win in stats["trades"]:
                if trade_ts is None:
                    continue
                try:
                    ts_val = trade_ts.timestamp() if hasattr(trade_ts, "timestamp") else time.mktime(trade_ts.timetuple()) if hasattr(trade_ts, "timetuple") else 0
                    cut_val = cutoff.timestamp() if hasattr(cutoff, "timestamp") else time.mktime(cutoff.timetuple())
                    if ts_val < cut_val:
                        continue
                except (TypeError, AttributeError, OSError):
                    continue  # skip trades with unparseable timestamps
                category_stats[cat]["trades"] += 1
                total_all_window_trades += 1
                if is_win:
                    category_stats[cat]["wins"] += 1
                else:
                    category_stats[cat]["losses"] += 1

        specialty_note = None
        specialty_category = None
        specialty_roi_pct = None

        min_spec_wins = int(config.get("vet_min_specialty_wins", 4) or 4)
        min_spec_trades = int(config.get("vet_min_specialty_trades", 10) or 10)
        min_cat_pct = float(config.get("vet_min_specialty_category_pct", 50) or 50)
        max_spec_losses = int(config.get("vet_max_specialty_losses", 0) or 0)

        if category_stats and total_all_window_trades > 0:
            top_cat = max(
                category_stats.items(),
                key=lambda x: (x[1]["wins"], x[1]["trades"]),
            )
            cat, stats = top_cat
            cw, cl, ct = stats["wins"], stats["losses"], stats["trades"]
            cat_pct = ct / total_all_window_trades * 100
            win_rate_cat = (cw / ct * 100) if ct > 0 else 0
            specialty_roi_pct = round(analysis.get("roi_pct", 0), 1)

            passes_wins = cw >= min_spec_wins
            passes_trades = ct >= min_spec_trades
            passes_focus = cat_pct >= min_cat_pct
            passes_losses = max_spec_losses <= 0 or cl <= max_spec_losses

            if passes_wins and passes_trades and passes_focus and passes_losses:
                specialty_category = cat
                specialty_note = (
                    f"Top category: {cat} ({cw}W/{ct}T, {win_rate_cat:.0f}% WR, "
                    f"{cat_pct:.0f}% focus, ROI {specialty_roi_pct}%)"
                )

        analysis["is_specialty"] = specialty_category is not None
        analysis["specialty_note"] = specialty_note
        analysis["specialty_market_id"] = None
        analysis["specialty_category"] = specialty_category
        analysis["specialty_roi_pct"] = specialty_roi_pct

        # Composite reliability score (0-100): long-term + recent + streak + conviction + trend, scaled by sample size.
        streak_score = min(analysis["current_win_streak"], 10) * 10
        trend_bonus = max(-10.0, min(10.0, analysis.get("win_rate_trend", 0.0))) * 0.5
        reliability_raw = (
            0.50 * analysis.get("win_rate_real", 0.0)
            + 0.25 * analysis.get("recent_win_rate", 0.0)
            + 0.15 * streak_score
            + 0.10 * analysis.get("conviction_score", 0.0)
            + trend_bonus
        )
        sample_factor = (
            min(1.0, resolved_decisions / 30.0) if resolved_decisions > 0 else 0.0
        )
        blended = reliability_raw * sample_factor + analysis.get(
            "win_rate_real", 0.0
        ) * (1 - sample_factor)
        analysis["reliability_score"] = round(max(0.0, min(100.0, blended)), 1)

        # Merge recent wins and specialty into one note (same alert)
        if specialty_note:
            analysis["specialty_or_hot_streak_note"] = specialty_note
        elif recent_wins >= config.vet_min_recent_wins:
            analysis["specialty_or_hot_streak_note"] = (
                f"Hot streak: {recent_wins} wins in last {min(window, len(resolved_trades_by_time))} resolved"
            )
        else:
            analysis["specialty_or_hot_streak_note"] = None

        if analysis["avg_bet_size"] < min_bet:
            analysis["issues"].append(
                f"Avg bet ${analysis['avg_bet_size']:.2f} below ${min_bet}"
            )

        max_bot = int(config.get("vet_max_bot_score", 70) or 70)
        if analysis["bot_score"] > max_bot:
            analysis["is_human"] = False
            analysis["issues"].append(
                f"Bot-like behavior (score: {analysis['bot_score']})"
            )

        max_unresolved = int(config.get("vet_max_unresolved_losses", 0) or 0)
        if max_unresolved > 0 and analysis["unsettled_loses"] > max_unresolved:
            analysis["is_settled"] = False
            analysis["issues"].append(f"{unresolved_losses} unresolved losses")

        min_resolved = int(config.get("vet_min_resolved_markets", 5) or 5)
        if analysis["resolved_markets_traded"] < min_resolved:
            analysis["issues"].append(f"Only {len(resolved_markets)} resolved markets")

        if config.vet_min_pnl > 0 and analysis.get("total_pnl", 0) < config.vet_min_pnl:
            analysis["issues"].append(
                f"PnL ${analysis.get('total_pnl', 0):.2f} below min ${config.vet_min_pnl}"
            )
        if analysis.get("trades_per_day", 0) > config.vet_max_trades_per_day:
            analysis["issues"].append(
                f"Arbitrage-like: {analysis.get('trades_per_day', 0):.1f} trades/day"
            )
        if (
            analysis.get("roi_pct", 0) < config.vet_min_roi_pct
            and config.vet_min_roi_pct > 0
        ):
            analysis["issues"].append(
                f"ROI {analysis.get('roi_pct', 0):.1f}% below min {config.vet_min_roi_pct}%"
            )
        if (
            analysis.get("conviction_score", 0) < config.vet_min_conviction
            and config.vet_min_conviction > 0
        ):
            analysis["issues"].append(
                f"Conviction {analysis.get('conviction_score', 0):.1f} below min {config.vet_min_conviction}"
            )
        if (
            config.vet_min_trades_won > 0
            and analysis.get("total_wins", 0) < config.vet_min_trades_won
        ):
            analysis["issues"].append(
                f"Wins {analysis.get('total_wins', 0)} below min {config.vet_min_trades_won}"
            )
        if (
            config.vet_max_losses > 0
            and analysis.get("total_losses", 0) > config.vet_max_losses
        ):
            analysis["issues"].append(
                f"Losses {analysis.get('total_losses', 0)} above max {config.vet_max_losses}"
            )
        min_streak = int(config.get("vet_min_current_win_streak", 0) or 0)
        if min_streak > 0 and analysis.get("current_win_streak", 0) < min_streak:
            analysis["issues"].append(
                f"Current streak {analysis.get('current_win_streak', 0)} below min {min_streak}"
            )
        min_reliability = float(config.get("vet_min_reliability_score", 0) or 0)
        if (
            min_reliability > 0
            and analysis.get("reliability_score", 0) < min_reliability
        ):
            analysis["issues"].append(
                f"Reliability {analysis.get('reliability_score', 0):.1f} below min {min_reliability:.1f}"
            )
        # Fee gate: Polymarket only; Kalshi/Jupiter bypass
        use_fee_gate = platform.lower() == "polymarket"
        if (
            use_fee_gate
            and config.vet_min_estimated_fees > 0
            and analysis.get("estimated_fees_paid", 0) < config.vet_min_estimated_fees
        ):
            analysis["issues"].append(
                f"Est. fees ${analysis.get('estimated_fees_paid', 0):.2f} below min ${config.vet_min_estimated_fees}"
            )

        # Baseline: human, settled, min bet, min markets, trades/day, wins, losses, fee gate (Polymarket only)
        min_resolved = int(config.get("vet_min_resolved_markets", 5) or 5)
        baseline = (
            analysis["is_human"]
            and analysis["is_settled"]
            and analysis["avg_bet_size"] >= min_bet
            and len(resolved_markets) >= min_resolved
            and analysis.get("trades_per_day", 0) <= config.vet_max_trades_per_day
            and analysis.get("total_wins", 0) >= config.vet_min_trades_won
            and (
                config.vet_max_losses <= 0
                or analysis.get("total_losses", 0) <= config.vet_max_losses
            )
            and (min_streak <= 0 or analysis.get("current_win_streak", 0) >= min_streak)
            and (
                min_reliability <= 0
                or analysis.get("reliability_score", 0) >= min_reliability
            )
            and (
                not use_fee_gate
                or config.vet_min_estimated_fees <= 0
                or analysis.get("estimated_fees_paid", 0)
                >= config.vet_min_estimated_fees
            )
        )
        # Normal pass: baseline + PnL/ROI/conviction gates
        normal_pass = (
            baseline
            and (
                config.vet_min_pnl <= 0
                or analysis.get("total_pnl", 0) >= config.vet_min_pnl
            )
            and (
                config.vet_min_roi_pct <= 0
                or analysis.get("roi_pct", 0) >= config.vet_min_roi_pct
            )
            and (
                config.vet_min_conviction <= 0
                or analysis.get("conviction_score", 0) >= config.vet_min_conviction
            )
        )
        # Specialty/hot-streak pass (merged): baseline + (specialty OR recent wins OR 5+ consecutive wins) AND total_pnl >= 0
        streak_threshold = int(config.get("win_streak_badge_threshold", 5) or 5)
        has_specialty_or_hot = (
            analysis.get("is_specialty")
            or analysis.get("recent_wins", 0) >= config.vet_min_recent_wins
            or analysis.get("max_win_streak", 0) >= streak_threshold
        )
        specialty_or_recent_pass = (
            baseline and has_specialty_or_hot and analysis.get("total_pnl", 0) >= 0
        )

        analysis["passed"] = normal_pass or specialty_or_recent_pass

        return analysis

    def _calculate_bot_score(self, trades: List[Dict]) -> int:
        """Calculate how likely a wallet is a bot (0-100).

        Fixed-weight per-wallet signals: each fires at most once. Score accumulates
        across independent signals; capped at 100. Threshold in config: vet_max_bot_score
        (default 70) — wallets above this fail the is_human gate.
        """
        if not trades or len(trades) < 5:
            return 0

        score = 0

        trade_times: List[datetime] = []
        prices: List[float] = []
        sizes_usd: List[float] = []
        for trade in trades:
            ts = trade.get("timestamp")
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        trade_times.append(datetime.fromtimestamp(float(ts)))
                    else:
                        trade_times.append(datetime.fromisoformat(str(ts).replace("Z", "")))
                except Exception:
                    pass
            price = float(trade.get("price", 0) or 0)
            size = float(trade.get("size", 0) or 0)
            if price > 0:
                prices.append(price)
            if price > 0 and size > 0:
                sizes_usd.append(size * price)

        # Signal: identical price across 60%+ of trades (+35)
        if len(prices) >= 10:
            from collections import Counter
            price_counts = Counter(round(p, 2) for p in prices)
            if price_counts.most_common(1)[0][1] >= len(prices) * 0.6:
                score += 35

        # Signal: avg inter-trade interval < 2s (+35) or < 5s (+15)
        if len(trade_times) > 15:
            intervals = [
                abs((trade_times[i] - trade_times[i - 1]).total_seconds())
                for i in range(1, min(30, len(trade_times)))
            ]
            avg_interval = sum(intervals) / len(intervals)
            if avg_interval < 2:
                score += 35
            elif avg_interval < 5:
                score += 15

        # Signal: inter-arrival CoV < 0.3 metronomic (+20) or <0.5 fast (+10)
        if len(trade_times) >= 10:
            gaps = [
                (trade_times[i] - trade_times[i - 1]).total_seconds()
                for i in range(1, len(trade_times))
            ]
            gaps = [g for g in gaps if g > 0]
            if len(gaps) >= 5:
                mean_gap = sum(gaps) / len(gaps)
                if mean_gap > 0:
                    std_gap = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
                    gap_cov = std_gap / mean_gap
                    if gap_cov < 0.3:
                        score += 20
                    elif gap_cov < 0.5 and mean_gap < 300:
                        score += 10

        # Signal: Gini of trade sizes < 0.15 = fixed-size betting (+20)
        if len(sizes_usd) >= 10:
            sorted_s = sorted(sizes_usd)
            n = len(sorted_s)
            sum_s = sum(sorted_s)
            if sum_s > 0:
                gini_num = sum((2 * (i + 1) - n - 1) * s for i, s in enumerate(sorted_s))
                gini = gini_num / (n * sum_s)
                if gini < 0.15:
                    score += 20

        # Signal: 24/7 uniform hourly distribution (entropy > 3.3 bits) (+15)
        # or heavy night concentration > 50% at 2-6 AM UTC (+10)
        if len(trade_times) >= 10:
            hour_counts = [0] * 24
            for t in trade_times:
                hour_counts[t.hour] += 1
            total_h = sum(hour_counts)
            probs = [c / total_h for c in hour_counts if c > 0]
            entropy = -sum(p * math.log2(p) for p in probs)
            if entropy > 3.3:
                score += 15
            else:
                night = sum(1 for t in trade_times if 2 <= t.hour <= 6)
                if night >= total_h * 0.5:
                    score += 10

        # Signal: formula-derived prices — <15% of prices land on 0.05 grid (+10)
        if len(prices) >= 10:
            round_count = sum(1 for p in prices if abs(round(p / 0.05) * 0.05 - p) < 0.001)
            if round_count / len(prices) < 0.15:
                score += 10

        return min(100, score)

    def _normalize_outcome(self, outcome: str) -> str:
        """Normalize outcome for comparison. Handles BUY_YES/Sell No etc. -> yes/no for binary."""
        o = (outcome or "").strip().lower()
        if not o:
            return o
        # Binary normalization (Polymarket Data API may return BUY_YES, Yes, etc.)
        if o in ("yes", "y", "buy_yes", "buy yes"):
            return "yes"
        if o in ("no", "n", "buy_no", "buy no"):
            return "no"
        return o

    def _resolve_trade_outcome(
        self, trade: Dict, market: Dict, price: float
    ) -> str:
        """Resolve trade's outcome: asset_id->token, else outcome/outcomeType, else price for binary."""
        outcome = (
            trade.get("outcome") or trade.get("outcomeType") or ""
        ).strip().lower()
        if outcome:
            return self._normalize_outcome(outcome)
        asset_id = (
            trade.get("asset_id")
            or trade.get("assetId")
            or trade.get("token_id")
            or (trade.get("raw") or {}).get("asset_id")
            or (trade.get("raw") or {}).get("assetId")
        )
        if asset_id and market:
            for t in market.get("tokens") or []:
                if isinstance(t, dict):
                    tid = t.get("token_id") or t.get("tokenId")
                    if str(tid) == str(asset_id):
                        o = (t.get("outcome") or "").strip().lower()
                        if o:
                            return self._normalize_outcome(o)
                        break
        return "no" if price < 0.5 else "yes"

    def _market_days_past_resolution(self, market: Dict) -> int:
        """Days since market endDate; 0 if unknown or in future."""
        end = market.get("endDate") or market.get("end_date") or market.get("end_date_iso")
        if not end:
            return 0
        try:
            if isinstance(end, (int, float)):
                end_ts = float(end)
            else:
                end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                end_ts = end_dt.timestamp()
            now_ts = time.time()
            return max(0, int((now_ts - end_ts) / 86400))
        except (ValueError, TypeError):
            return 0

    def _has_closed_position(self, address: str, market_id: str) -> bool:
        """Check if wallet has closed their position in a market (single-call version)."""
        try:
            positions = self.api.get_wallet_positions(address) if self.api else []
        except Exception as e:
            logger.debug("Vetting _has_closed_position error: %s", e)
            positions = []
        return self._has_closed_position_from_cache(positions, market_id)

    def _has_closed_position_from_cache(self, positions: list, market_id: str) -> bool:
        """Check pre-fetched positions list — avoids repeated API calls per vet."""
        for pos in positions:
            pos_market = pos.get("conditionId") or pos.get("market")
            if pos_market == market_id:
                return False
        return True

    def get_vetted_wallets(
        self,
        addresses: List[str],
        min_bet: float = 10,
        min_win_rate: float = 55,
        min_pnl: Optional[float] = None,
        min_roi: Optional[float] = None,
        platform: str = "polymarket",
    ) -> List[Dict]:
        """Vet multiple wallets and return qualified ones.

        Polymarket: specialty/recent-wins merge then fee gate (sequential).
        Kalshi/Jupiter: bypass fee gate.

        Args:
            addresses: List of wallet addresses
            min_bet: Minimum average bet size
            min_win_rate: Minimum win rate on resolved markets
            min_pnl: Optional minimum total PnL (USD) to include
            min_roi: Optional minimum ROI % to include
            platform: polymarket (fee gate), kalshi or jupiter (bypass fee)

        Returns:
            List of vetted wallets that pass criteria
        """
        qualified = []
        for addr in addresses:
            result = self.vet_wallet(addr, min_bet, platform=platform)
            if result and result["passed"]:
                if result["win_rate_real"] < min_win_rate:
                    continue
                if min_pnl is not None and result.get("total_pnl", 0) < min_pnl:
                    continue
                if min_roi is not None and result.get("roi_pct", 0) < min_roi:
                    continue
                qualified.append(result)

        return qualified
