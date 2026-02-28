"""Advanced wallet vetting for PolySuite - filters bots and P&L cheaters.

Fee-based filtering: Polymarket charges 2% only on winning bets, so estimated_fees_paid
proxies for winning volume. Kalshi: /portfolio/fills returns fee_cost but requires auth
(your account only); no public endpoint for other users' fees.
"""

from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from src.market.api import APIClientFactory
from src.config import Config


class WalletVetting:
    """Vet wallets to filter out bots and P&L cheaters."""

    def __init__(self, api_factory: APIClientFactory):
        self.api = api_factory.get_polymarket_api()

    def vet_wallet(
        self,
        address: str,
        min_bet: float = 10,
        platform: str = "polymarket",
        market_cache: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Fully vet a wallet and return analysis.

        Polymarket: sequential flow - specialty/recent-wins merge, then fee gate.
        Kalshi/Jupiter: bypass fee gate (no fee data available).

        Args:
            address: Wallet address
            min_bet: Minimum average bet size to qualify
            platform: "polymarket" (default), "kalshi", or "jupiter" - fee gate only for polymarket

        Returns:
            Dict with vetting results or None if failed
        """
        trades = self.api.get_wallet_trades(address, limit=500)
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
        for mid in market_ids:
            if mid not in market_cache:
                market_cache[mid] = self.api.get_market(mid)

        for trade, market_id in trade_market_map:
            size = float(trade.get("size", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            side = trade.get("side", "").upper()
            usd = size * price
            total_volume += usd

            market = market_cache.get(market_id)
            if market:
                cat = (market.get("category") or "other").lower()
                category_volume[cat] = category_volume.get(cat, 0) + usd
            if market:
                resolved = market.get("resolved") or market.get("closed")
                if resolved:
                    resolved_markets.add(market_id)

                    winning_outcome = (market.get("outcome") or "").lower()
                    if winning_outcome:
                        # Use trade outcome (YES/NO) - prefer explicit field, else infer from price
                        trade_outcome = (trade.get("outcome") or trade.get("outcomeType") or "").lower()
                        if not trade_outcome:
                            # Infer from price: < 0.5 typically NO, else YES
                            trade_outcome = "no" if price < 0.5 else "yes"
                        # Win: bought winning side, or sold losing side before resolution
                        # Loss: bought losing side, or sold winning side (gave up the win)
                        is_win = False
                        is_loss = False
                        if trade_outcome == winning_outcome and side == "BUY":
                            wins += 1
                            is_win = True
                        elif trade_outcome != winning_outcome and side == "SELL":
                            wins += 1
                            is_win = True
                        elif trade_outcome != winning_outcome and side == "BUY":
                            if not self._has_closed_position(address, market_id):
                                unresolved_losses += 1
                            is_loss = True
                        elif trade_outcome == winning_outcome and side == "SELL":
                            # Sold winning position before resolution - loss (not counted as win)
                            is_loss = True

                        # Collect for recent wins and per-market specialty
                        ts = trade.get("timestamp") or trade.get("matchTime") or trade.get("match_time") or trade.get("createdAt")
                        trade_ts = None
                        if ts:
                            try:
                                if isinstance(ts, (int, float)):
                                    trade_ts = datetime.fromtimestamp(float(ts))
                                else:
                                    trade_ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                            except (ValueError, TypeError):
                                pass
                        if trade_ts and (is_win or is_loss):
                            resolved_trades_by_time.append((trade_ts, market_id, is_win))
                            if market_id not in market_stats:
                                market_stats[market_id] = {"wins": 0, "losses": 0, "trades": []}
                            market_stats[market_id]["trades"].append((trade_ts, is_win))
                            if is_win:
                                market_stats[market_id]["wins"] += 1
                            else:
                                market_stats[market_id]["losses"] += 1

        analysis["total_volume"] = total_volume
        analysis["avg_bet_size"] = total_volume / len(trades) if trades else 0
        analysis["top_category"] = max(category_volume, key=category_volume.get) if category_volume else None
        analysis["resolved_markets_traded"] = len(resolved_markets)

        if len(resolved_markets) > 0:
            analysis["win_rate_real"] = (wins / len(resolved_markets)) * 100

        analysis["unsettled_loses"] = unresolved_losses
        analysis["bot_score"] = self._calculate_bot_score(trades)

        # Smart money metrics
        total_pnl = 0
        estimated_fees = 0
        try:
            closed = self.api.get_closed_positions(address, limit=100)
            for pos in closed or []:
                pnl = pos.get("realizedPnl") or pos.get("realized_pnl")
                if pnl is not None:
                    p = float(pnl)
                    total_pnl += p
                    if p > 0:
                        estimated_fees += p * (0.02 / 0.98)
        except Exception as e:
            print(f"[Vetting] get_closed_positions error: {e}")
        analysis["total_pnl"] = total_pnl
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
            ts = trade.get("timestamp") or trade.get("matchTime") or trade.get("match_time") or trade.get("createdAt")
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        trade_times.append(datetime.fromtimestamp(float(ts)))
                    else:
                        trade_times.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
                except (ValueError, TypeError):
                    pass
        if trade_sizes:
            sorted_sizes = sorted(trade_sizes)
            n = len(sorted_sizes)
            percentiles = []
            for s in trade_sizes:
                if s <= 0:
                    percentiles.append(0)
                else:
                    rank = sum(1 for x in sorted_sizes if x < s)
                    percentiles.append((rank / n) * 100 if n > 0 else 0)
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
        max_position_pct = (max_market_vol / total_volume * 100) if total_volume > 0 else 0
        analysis["max_position_pct"] = round(max_position_pct, 1)

        # Recent wins: count wins in last N resolved trades (by time)
        config = Config()
        resolved_trades_by_time.sort(key=lambda x: x[0])
        window = config.vet_recent_wins_window
        last_n = resolved_trades_by_time[-window:] if len(resolved_trades_by_time) > window else resolved_trades_by_time
        recent_wins = sum(1 for _, _, w in last_n if w)
        analysis["recent_wins"] = recent_wins

        # Specialty: per-market high success (multiple wins in a row, low losses)
        min_spec_wins = config.vet_min_specialty_wins
        min_spec_streak = config.vet_min_specialty_streak
        max_spec_losses = config.vet_max_specialty_losses
        specialty_market = None
        specialty_note = None
        specialty_category = None
        for mid, stats in market_stats.items():
            if stats["wins"] < min_spec_wins or stats["losses"] > max_spec_losses:
                continue
            trades_ordered = sorted(stats["trades"], key=lambda x: x[0])
            streak = 0
            max_streak = 0
            for _, is_win in trades_ordered:
                if is_win:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 0
            if max_streak >= min_spec_streak:
                m = market_cache.get(mid)
                q = (m.get("question") or "Unknown")[:50] if m else "Unknown"
                cat = (m.get("category") or "other") if m else "other"
                specialty_market = mid
                specialty_note = f"Specialty: {q}... ({stats['wins']}W/{stats['losses']}L, streak {max_streak})"
                specialty_category = cat
                break
        analysis["is_specialty"] = specialty_market is not None
        analysis["specialty_note"] = specialty_note
        analysis["specialty_market_id"] = specialty_market
        analysis["specialty_category"] = specialty_category

        # Total wins/losses from resolved markets
        analysis["total_wins"] = wins
        analysis["total_losses"] = sum(s["losses"] for s in market_stats.values())

        # Merge recent wins and specialty into one note (same alert)
        if specialty_note:
            analysis["specialty_or_hot_streak_note"] = specialty_note
        elif recent_wins >= config.vet_min_recent_wins:
            analysis["specialty_or_hot_streak_note"] = f"Hot streak: {recent_wins} wins in last {min(window, len(resolved_trades_by_time))} resolved"
        else:
            analysis["specialty_or_hot_streak_note"] = None

        if analysis["avg_bet_size"] < min_bet:
            analysis["issues"].append(
                f"Avg bet ${analysis['avg_bet_size']:.2f} below ${min_bet}"
            )

        if analysis["bot_score"] > 70:
            analysis["is_human"] = False
            analysis["issues"].append(
                f"Bot-like behavior (score: {analysis['bot_score']})"
            )

        if analysis["unsettled_loses"] > 3:
            analysis["is_settled"] = False
            analysis["issues"].append(f"{unresolved_losses} unresolved losses")

        if analysis["resolved_markets_traded"] < 5:
            analysis["issues"].append(f"Only {len(resolved_markets)} resolved markets")

        if config.vet_min_pnl > 0 and analysis.get("total_pnl", 0) < config.vet_min_pnl:
            analysis["issues"].append(
                f"PnL ${analysis.get('total_pnl', 0):.2f} below min ${config.vet_min_pnl}"
            )
        if analysis.get("trades_per_day", 0) > config.vet_max_trades_per_day:
            analysis["issues"].append(
                f"Arbitrage-like: {analysis.get('trades_per_day', 0):.1f} trades/day"
            )
        if analysis.get("roi_pct", 0) < config.vet_min_roi_pct and config.vet_min_roi_pct > 0:
            analysis["issues"].append(
                f"ROI {analysis.get('roi_pct', 0):.1f}% below min {config.vet_min_roi_pct}%"
            )
        if analysis.get("conviction_score", 0) < config.vet_min_conviction and config.vet_min_conviction > 0:
            analysis["issues"].append(
                f"Conviction {analysis.get('conviction_score', 0):.1f} below min {config.vet_min_conviction}"
            )
        if config.vet_min_trades_won > 0 and analysis.get("total_wins", 0) < config.vet_min_trades_won:
            analysis["issues"].append(
                f"Wins {analysis.get('total_wins', 0)} below min {config.vet_min_trades_won}"
            )
        if config.vet_max_losses > 0 and analysis.get("total_losses", 0) > config.vet_max_losses:
            analysis["issues"].append(
                f"Losses {analysis.get('total_losses', 0)} above max {config.vet_max_losses}"
            )
        # Fee gate: Polymarket only; Kalshi/Jupiter bypass
        use_fee_gate = platform.lower() == "polymarket"
        if use_fee_gate and config.vet_min_estimated_fees > 0 and analysis.get("estimated_fees_paid", 0) < config.vet_min_estimated_fees:
            analysis["issues"].append(
                f"Est. fees ${analysis.get('estimated_fees_paid', 0):.2f} below min ${config.vet_min_estimated_fees}"
            )

        # Baseline: human, settled, min bet, min markets, trades/day, wins, losses, fee gate (Polymarket only)
        baseline = (
            analysis["is_human"]
            and analysis["is_settled"]
            and analysis["avg_bet_size"] >= min_bet
            and len(resolved_markets) >= 5
            and analysis.get("trades_per_day", 0) <= config.vet_max_trades_per_day
            and analysis.get("total_wins", 0) >= config.vet_min_trades_won
            and (config.vet_max_losses <= 0 or analysis.get("total_losses", 0) <= config.vet_max_losses)
            and (not use_fee_gate or config.vet_min_estimated_fees <= 0 or analysis.get("estimated_fees_paid", 0) >= config.vet_min_estimated_fees)
        )
        # Normal pass: baseline + PnL/ROI/conviction gates
        normal_pass = (
            baseline
            and (config.vet_min_pnl <= 0 or analysis.get("total_pnl", 0) >= config.vet_min_pnl)
            and (config.vet_min_roi_pct <= 0 or analysis.get("roi_pct", 0) >= config.vet_min_roi_pct)
            and (config.vet_min_conviction <= 0 or analysis.get("conviction_score", 0) >= config.vet_min_conviction)
        )
        # Specialty/hot-streak pass (merged): baseline + (specialty OR recent wins) AND total_pnl >= 0 (no losing records)
        has_specialty_or_hot = analysis.get("is_specialty") or analysis.get("recent_wins", 0) >= config.vet_min_recent_wins
        specialty_or_recent_pass = (
            baseline
            and has_specialty_or_hot
            and analysis.get("total_pnl", 0) >= 0
        )

        analysis["passed"] = normal_pass or specialty_or_recent_pass

        return analysis

    def _calculate_bot_score(self, trades: List[Dict]) -> int:
        """Calculate how likely a wallet is a bot (0-100).

        Indicators: round-number sizes, identical prices, 24/7 trading,
        instant in/out, high-frequency intervals.
        """
        if not trades:
            return 0

        bot_indicators = 0
        total = 0

        trade_times = []
        sizes = []
        prices = []
        for i, trade in enumerate(trades):
            total += 1

            ts = trade.get("timestamp")
            if ts:
                try:
                    trade_times.append(datetime.fromisoformat(ts.replace("Z", "")))
                except Exception as e:
                    print(f"[Vetting] timestamp parse: {e}")

            size = float(trade.get("size", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            sizes.append(size)
            prices.append(price)

            # Round-number sizes (100, 500, 1000, 5000, etc.)
            if size > 0 and size == round(size) and size in (100, 500, 1000, 5000, 10000):
                bot_indicators += 1
            elif size > 1000:
                bot_indicators += 1

            # Instant in/out (< 1s between trades)
            if i > 0 and len(trade_times) > 1:
                if (trade_times[-1] - trade_times[-2]).total_seconds() < 1:
                    bot_indicators += 2

        # Identical price across many trades (bot-like)
        if len(prices) >= 5:
            from collections import Counter
            price_counts = Counter(round(p, 2) for p in prices if p > 0)
            most_common = price_counts.most_common(1)
            if most_common and most_common[0][1] >= len(prices) * 0.5:
                bot_indicators += 3

        # 24/7 trading (trades at odd hours: 2-6 AM UTC suggests bot)
        if len(trade_times) >= 5:
            night_trades = sum(1 for t in trade_times if 2 <= t.hour <= 6)
            if night_trades >= len(trade_times) * 0.4:
                bot_indicators += 2

        # High-frequency intervals
        if len(trade_times) > 10:
            intervals = []
            for i in range(1, min(20, len(trade_times))):
                intervals.append((trade_times[i] - trade_times[i - 1]).total_seconds())

            avg_interval = sum(intervals) / len(intervals)
            if avg_interval < 5:
                bot_indicators += 5
            if avg_interval < 1:
                bot_indicators += 10

        return min(100, int((bot_indicators / max(total, 1)) * 100))

    def _has_closed_position(self, address: str, market_id: str) -> bool:
        """Check if wallet has closed their position in a market."""
        try:
            positions = self.api.get_wallet_positions(address) if self.api else []
        except Exception as e:
            print(f"[Vetting] _has_closed_position error: {e}")
            positions = []
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
        config = Config()

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
