"""Wallet Classifier - Advanced scoring and classification for PolySuite wallets.

This module provides comprehensive wallet analysis to identify:
- Bots and automated traders
- Farmers (high volume, low profit)
- High loss rate traders
- Consistent winners with win streaks
- Recent and current performance focus (7-day, 14-day)

Scoring prioritizes recent performance over lifetime stats.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import math
import random
import statistics

from src.market.api import extract_market_category


class WalletClassification(Enum):
    """Wallet classification types."""

    BOT = "bot"
    FARMER = "farmer"
    HIGH_LOSS_RATE = "high_loss_rate"
    INCONSISTENT = "inconsistent"
    AVERAGE = "average"
    GOOD = "good"
    EXCELLENT = "excellent"
    WIN_STREAK = "win_streak"


@dataclass
class TradeAnalysis:
    """Individual trade analysis."""

    timestamp: Optional[datetime]
    size: float
    price: float
    usd_value: float
    side: str  # BUY/SELL
    is_win: bool = False
    is_loss: bool = False
    market_id: Optional[str] = None
    category: Optional[str] = None
    resolved: bool = False
    outcome: Optional[str] = None


@dataclass
class TimeWindowStats:
    """Stats for a specific time window."""

    period_days: int
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_volume: float = 0
    total_pnl: float = 0
    avg_trade_size: float = 0
    avg_pnl_per_trade: float = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # gross wins / gross losses


@dataclass
class WalletScore:
    """Comprehensive wallet score and classification."""

    address: str
    nickname: Optional[str] = None

    # Overall score (0-100)
    total_score: float = 0.0

    # Classification
    classification: WalletClassification = WalletClassification.AVERAGE
    classification_reason: str = ""

    # Time-based stats (priority)
    stats_7d: Optional[TimeWindowStats] = None
    stats_14d: Optional[TimeWindowStats] = None
    stats_30d: Optional[TimeWindowStats] = None
    stats_lifetime: Optional[TimeWindowStats] = None

    # Win streaks
    current_win_streak: int = 0
    max_win_streak: int = 0
    recent_win_streak: int = 0  # Last 7 days

    # Flags
    is_bot: bool = False
    is_farmer: bool = False
    is_high_loss_rate: bool = False
    has_unresolved_positions: bool = False
    is_inconsistent: bool = False

    # Detailed metrics
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    win_rate: float = 0.0
    avg_trade_size: float = 0.0
    total_volume: float = 0.0
    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0

    # Risk metrics
    unresolved_count: int = 0
    unresolved_volume: float = 0.0
    loss_rate: float = 0.0
    profit_factor: float = 0.0

    # Activity metrics
    trades_per_day: float = 0.0
    avg_time_between_trades_hours: float = 0.0
    trade_size_std_dev: float = 0.0

    # Metadata
    first_trade_date: Optional[datetime] = None
    last_trade_date: Optional[datetime] = None
    days_active: int = 0

    # Detailed flags
    bot_flags: List[str] = field(default_factory=list)
    farmer_flags: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    positives: List[str] = field(default_factory=list)

    # Tier system
    tier: str = "watch"

    # New data points
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    specialty_category: Optional[str] = None
    specialty_category_2: Optional[str] = None
    specialty_win_rate: float = 0.0
    specialty_volume: float = 0.0
    specialty_roi_pct: Optional[float] = None
    avg_hold_duration_hours: float = 0.0
    preferred_odds_range: str = "medium"
    size_consistency: float = 0.0
    volume_weighted_win_rate: float = 0.0

    # Pattern tracking
    trading_hours: dict = field(default_factory=dict)
    trading_days: dict = field(default_factory=dict)
    odds_distribution: dict = field(default_factory=dict)
    category_stats: dict = field(default_factory=dict)


class WalletClassifier:
    """Classify and score wallets based on trading behavior."""

    # Thresholds
    BOT_TRADES_PER_DAY_THRESHOLD = 200  # More than 200 trades/day = likely bot
    BOT_TRADE_INTERVAL_MINUTES = 1  # Less than 1 min avg = likely bot
    BOT_SIZE_STD_DEV_THRESHOLD = 0.02  # Very consistent sizes = likely bot

    FARMER_MIN_TRADES = 500
    FARMER_MIN_VOLUME = 100000
    FARMER_MAX_AVG_PNL = 0.01  # Less than 1 cent avg = farming

    HIGH_LOSS_RATE_THRESHOLD = 70  # More than 70% losses

    UNRESOLVED_THRESHOLD = 20  # More than 20 unresolved = concerning

    # Scoring weights (must sum to 1.0)
    WEIGHT_7D = 0.35
    WEIGHT_14D = 0.25
    WEIGHT_30D = 0.15
    WEIGHT_LIFETIME = 0.10
    WEIGHT_WIN_STREAK = 0.10
    WEIGHT_CONSISTENCY = 0.05

    # Minimum thresholds for scoring
    MIN_TRADES_FOR_7D = 3
    MIN_TRADES_FOR_14D = 5
    MIN_TRADES_FOR_CLASSIFICATION = 10

    def __init__(self, api_client=None):
        self.api = api_client

    def classify_wallet(
        self,
        address: str,
        trades: List[Dict],
        nickname: Optional[str] = None,
        existing_wallet=None,
        market_cache: Optional[Dict] = None,
    ) -> WalletScore:
        """Classify a wallet based on trade history.

        Args:
            address: Wallet address
            trades: List of trade dicts from API
            nickname: Optional nickname
            existing_wallet: Optional existing Wallet object with stored stats
        """

        score = WalletScore(address=address, nickname=nickname)

        if not trades:
            score.classification = WalletClassification.INCONSISTENT
            score.classification_reason = "No trades found"
            return score

        # Parse trades
        trade_analyses = self._parse_trades(trades)
        if not trade_analyses:
            score.classification = WalletClassification.INCONSISTENT
            score.classification_reason = "Could not parse trades"
            return score

        # Resolve win/loss from market data (required for score, specialty, streaks)
        self._resolve_trade_outcomes(
            trade_analyses,
            trades,
            wallet_address=address,
            external_market_cache=market_cache,
        )

        # Aggregate totals come from _calculate_overall_stats (resolved-aware), not stale DB.

        # Calculate time window stats
        score.stats_7d = self._calculate_time_window(trade_analyses, 7)
        score.stats_14d = self._calculate_time_window(trade_analyses, 14)
        score.stats_30d = self._calculate_time_window(trade_analyses, 30)
        score.stats_lifetime = self._calculate_time_window(trade_analyses, None)

        # Calculate overall stats
        self._calculate_overall_stats(score, trade_analyses, existing_wallet)

        # Detect patterns
        self._detect_bots(score, trade_analyses)
        self._detect_farmers(score, trade_analyses)
        self._detect_high_loss_rate(score)
        self._detect_unresolved_positions(score, trade_analyses)
        self._calculate_win_streaks(score, trade_analyses)
        self._calculate_activity_metrics(score, trade_analyses)

        # Calculate patterns and category breakdown
        self._calculate_patterns(score, trade_analyses)
        self._calculate_category_breakdown(score)
        self._calculate_volume_weighted_win_rate(score, trade_analyses)
        self._calculate_consecutive_losses(score, trade_analyses)

        # Calculate final score
        score.total_score = self._calculate_score(score)

        # Determine classification
        score.classification = self._determine_classification(score)

        # Determine tier
        score.tier = self._determine_tier(score)

        return score

    def _parse_trades(self, trades: List[Dict]) -> List[TradeAnalysis]:
        """Parse raw trades into structured analysis."""
        parsed = []

        for trade in trades:
            try:
                ts = (
                    trade.get("timestamp")
                    or trade.get("matchTime")
                    or trade.get("createdAt")
                )
                timestamp = None
                if ts:
                    try:
                        if isinstance(ts, (int, float)):
                            timestamp = datetime.fromtimestamp(float(ts))
                        else:
                            timestamp = datetime.fromisoformat(
                                str(ts).replace("Z", "+00:00")
                            )
                    except (ValueError, TypeError):
                        pass

                size = float(trade.get("size", 0) or 0)
                price = float(trade.get("price", 0) or 0)

                analysis = TradeAnalysis(
                    timestamp=timestamp,
                    size=size,
                    price=price,
                    usd_value=size * price,
                    side=(trade.get("side") or "BUY").upper(),
                    market_id=trade.get("conditionId") or trade.get("market"),
                    category=trade.get("category"),
                    resolved=trade.get("resolved", False),
                    outcome=(trade.get("outcome") or trade.get("outcomeType") or "").lower(),
                )
                parsed.append(analysis)
            except Exception:
                continue

        # Sort by timestamp
        parsed.sort(key=lambda x: x.timestamp or datetime.min)
        return parsed

    MAX_MARKETS_TO_RESOLVE = 140  # Cap API calls; split top-by-volume + random tail for category coverage

    def _resolve_trade_outcomes(
        self,
        trade_analyses: List[TradeAnalysis],
        raw_trades: List[Dict],
        wallet_address: str = "",
        external_market_cache: Optional[Dict] = None,
    ) -> None:
        """Resolve win/loss for each trade using market data. Required for score, specialty, streaks.

        Always attaches *category* from Gamma/CLOB when the market is fetched, even if the
        market is still open — otherwise specialty/category stats stay empty for active bettors.
        Win/loss flags are only set for resolved markets with a known winning outcome.
        """
        if not self.api:
            return

        # Build market_id -> trades (ta has outcome, side from parse)
        mid_to_trades: Dict[str, List[TradeAnalysis]] = {}
        for ta in trade_analyses:
            mid = ta.market_id
            if not mid:
                continue
            mid_to_trades.setdefault(mid, []).append(ta)

        # Cap markets: (1) heaviest markets first for win/loss, (2) random sample of the
        # rest so specialty isn't empty when activity is spread across many markets.
        all_keys = [m for m in mid_to_trades.keys() if m]
        sorted_keys = sorted(
            all_keys, key=lambda m: len(mid_to_trades[m]), reverse=True
        )
        cap = self.MAX_MARKETS_TO_RESOLVE
        top_n = min(80, cap)
        market_ids = list(sorted_keys[:top_n])
        rest = [m for m in sorted_keys[top_n:] if m]
        remain = cap - len(market_ids)
        if rest and remain > 0:
            k = min(remain, len(rest))
            seed = int(
                hashlib.md5((wallet_address or "x").lower().encode()).hexdigest()[:8],
                16,
            )
            rng = random.Random(seed)
            market_ids.extend(rng.sample(rest, k))
        if external_market_cache is not None:
            market_cache = external_market_cache
        else:
            market_cache = {}

        # Parallel market fetches — same fix as vetting.py N+1 bottleneck
        to_fetch = [mid for mid in market_ids if mid not in market_cache]
        if to_fetch:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            def _fetch(mid):
                try:
                    return mid, self.api.get_market(mid)
                except Exception:
                    return mid, None
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {pool.submit(_fetch, mid): mid for mid in to_fetch}
                for fut in as_completed(futures):
                    mid, result = fut.result()
                    market_cache[mid] = result

        for mid, analyses in mid_to_trades.items():
            market = market_cache.get(mid)
            if not market:
                continue

            # Category for pattern + specialty (resolved or not)
            cat = extract_market_category(market) or (
                (market.get("category") or "other").strip().lower()
            )
            for ta in analyses:
                if not ta.category:
                    ta.category = cat

            resolved = market.get("resolved") or market.get("closed")
            if not resolved:
                continue
            winning_outcome = (market.get("outcome") or "").lower()
            if not winning_outcome:
                continue

            for ta in analyses:
                trade_outcome = (ta.outcome or "").lower()
                if not trade_outcome:
                    trade_outcome = "no" if (ta.price or 0) < 0.5 else "yes"
                side = (ta.side or "BUY").upper()

                if trade_outcome == winning_outcome and side == "BUY":
                    ta.is_win = True
                elif trade_outcome != winning_outcome and side == "SELL":
                    ta.is_win = True
                elif trade_outcome != winning_outcome and side == "BUY":
                    ta.is_loss = True
                elif trade_outcome == winning_outcome and side == "SELL":
                    ta.is_loss = True

    def _calculate_time_window(
        self, trades: List[TradeAnalysis], days: Optional[int]
    ) -> Optional[TimeWindowStats]:
        """Calculate stats for a specific time window."""
        if not trades:
            return None

        now = trades[-1].timestamp if trades else datetime.now()
        if days is not None:
            cutoff = now - timedelta(days=days)
            window_trades = [t for t in trades if t.timestamp and t.timestamp >= cutoff]
        else:
            window_trades = trades

        if not window_trades:
            return None

        stats = TimeWindowStats(period_days=days or 999)
        stats.total_trades = len(window_trades)

        wins = 0
        losses = 0
        total_vol = 0
        pnl = 0

        for trade in window_trades:
            total_vol += trade.usd_value
            if trade.is_win:
                wins += 1
                pnl += trade.usd_value * (1 - trade.price)  # Simplified PnL
            elif trade.is_loss:
                losses += 1
                pnl -= trade.usd_value * trade.price

        stats.wins = wins
        stats.losses = losses
        stats.total_volume = total_vol
        stats.total_pnl = pnl
        stats.avg_trade_size = (
            total_vol / stats.total_trades if stats.total_trades > 0 else 0
        )
        stats.avg_pnl_per_trade = (
            pnl / stats.total_trades if stats.total_trades > 0 else 0
        )
        stats.win_rate = (
            (wins / stats.total_trades * 100) if stats.total_trades > 0 else 0
        )

        # Profit factor
        gross_wins = sum(t.usd_value * (1 - t.price) for t in window_trades if t.is_win)
        gross_losses = sum(t.usd_value * t.price for t in window_trades if t.is_loss)
        stats.profit_factor = (
            gross_wins / gross_losses
            if gross_losses > 0
            else float("inf")
            if gross_wins > 0
            else 0
        )

        return stats

    def _calculate_overall_stats(
        self, score: WalletScore, trades: List[TradeAnalysis], existing_wallet=None
    ):
        """Calculate overall statistics from trade analysis (resolved win/loss when available)."""
        score.total_trades = len(trades)
        score.total_volume = sum(t.usd_value for t in trades)
        rw = sum(1 for t in trades if t.is_win)
        rl = sum(1 for t in trades if t.is_loss)
        score.wins = rw
        score.losses = rl
        denom = rw + rl
        if denom > 0:
            score.win_rate = (rw / denom) * 100.0
        elif existing_wallet:
            # No resolved outcomes in this sample — keep stored rate as weak fallback
            score.win_rate = float(getattr(existing_wallet, "win_rate", 0) or 0)
            score.wins = int(getattr(existing_wallet, "wins", 0) or 0)
            et = int(getattr(existing_wallet, "total_trades", 0) or 0)
            score.losses = max(0, et - score.wins)
        else:
            score.win_rate = 0.0

        score.loss_rate = 100 - score.win_rate

        score.avg_trade_size = (
            score.total_volume / score.total_trades if score.total_trades > 0 else 0
        )
        score.avg_pnl_per_trade = (
            score.total_pnl / score.total_trades if score.total_trades > 0 else 0
        )

        # Dates
        if trades:
            timestamps = [t.timestamp for t in trades if t.timestamp]
            if timestamps:
                score.first_trade_date = min(timestamps)
                score.last_trade_date = max(timestamps)
                delta = score.last_trade_date - score.first_trade_date
                score.days_active = max(1, delta.days)

        # PnL: prefer vetting-quality closed PnL from DB if present
        if existing_wallet and getattr(existing_wallet, "total_pnl", None) is not None:
            score.total_pnl = float(existing_wallet.total_pnl)
        else:
            total_pnl = 0.0
            for t in trades:
                if t.is_win:
                    total_pnl += t.usd_value * (1 - t.price)
                elif t.is_loss:
                    total_pnl -= t.usd_value * t.price
            score.total_pnl = total_pnl
        score.avg_pnl_per_trade = (
            total_pnl / score.total_trades if score.total_trades > 0 else 0
        )

        # Dates
        if trades:
            score.first_trade_date = trades[0].timestamp
            score.last_trade_date = trades[-1].timestamp
            if trades[0].timestamp and trades[-1].timestamp:
                delta = trades[-1].timestamp - trades[0].timestamp
                score.days_active = max(1, delta.days)

    def _detect_bots(self, score: WalletScore, trades: List[TradeAnalysis]):
        """Multi-signal bot detection based on research signals.

        Triggered when:
          - ≥1 HIGH signal, OR
          - ≥2 MEDIUM signals
        """
        if len(trades) < 10:
            return

        HIGH, MEDIUM = "high", "medium"
        flags: List[tuple] = []  # (weight, description)

        # Hard gate: extreme frequency + uniform sizes (instant trip)
        if score.trades_per_day > 200 and score.trade_size_std_dev < 0.05:
            score.is_bot = True
            score.bot_flags.append(
                f"High frequency uniform sizing: {score.trades_per_day:.0f}/day"
            )
            return

        # --- Signal 1: Trades per day (raw frequency) ---
        if score.trades_per_day > 100:
            flags.append((HIGH, f"Extreme trade frequency: {score.trades_per_day:.0f}/day"))
        elif score.trades_per_day > 50:
            flags.append((MEDIUM, f"Very high trade frequency: {score.trades_per_day:.0f}/day"))

        # --- Signal 2: Inter-arrival time CoV (metronomic = bot) ---
        times = sorted(t.timestamp for t in trades if t.timestamp)
        if len(times) >= 10:
            gaps = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
            gaps = [g for g in gaps if g > 0]
            if len(gaps) >= 5:
                mean_gap = statistics.mean(gaps)
                std_gap = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
                gap_cov = std_gap / mean_gap if mean_gap > 0 else 0.0
                if gap_cov < 0.5 and mean_gap < 600:
                    flags.append((HIGH, f"Metronomic fast timing: gap CoV={gap_cov:.2f}, mean={mean_gap:.0f}s"))
                elif gap_cov < 0.7:
                    flags.append((MEDIUM, f"Regular timing pattern: gap CoV={gap_cov:.2f}"))

        # --- Signal 3: Gini coefficient of trade sizes ---
        sizes = sorted(t.usd_value for t in trades if t.usd_value > 0)
        if len(sizes) >= 10:
            n = len(sizes)
            sum_s = sum(sizes)
            if sum_s > 0:
                gini_num = sum((2 * (i + 1) - n - 1) * s for i, s in enumerate(sizes))
                gini = gini_num / (n * sum_s)
                if gini < 0.20:
                    flags.append((HIGH, f"Fixed-size betting: Gini={gini:.3f} (no sizing variation)"))
                elif gini < 0.30:
                    flags.append((MEDIUM, f"Near-uniform sizing: Gini={gini:.3f}"))
                elif gini > 0.85:
                    flags.append((MEDIUM, f"Extreme size skew: Gini={gini:.3f} (dump/farming pattern)"))

        # --- Signal 4: Hourly entropy (cron-bot or 24/7-bot) ---
        if len(times) >= 10:
            hour_counts = [0] * 24
            for t in times:
                hour_counts[t.hour] += 1
            total_h = sum(hour_counts)
            probs = [c / total_h for c in hour_counts if c > 0]
            entropy = -sum(p * math.log2(p) for p in probs)
            if entropy > 3.1:
                flags.append((MEDIUM, f"24/7 trading: hourly entropy={entropy:.2f} bits (no sleep gap)"))
            elif entropy < 1.2:
                flags.append((MEDIUM, f"Cron-like schedule: hourly entropy={entropy:.2f} bits"))

        # --- Signal 5: Round-number price ratio (formula-priced = bot) ---
        prices = [t.price for t in trades if 0 < t.price < 1]
        if len(prices) >= 10:
            round_count = sum(1 for p in prices if abs(round(p / 0.05) * 0.05 - p) < 0.001)
            round_ratio = round_count / len(prices)
            if round_ratio < 0.10:
                flags.append((HIGH, f"Formula-derived prices: {round_ratio:.0%} round (AMM/arb pattern)"))
            elif round_ratio < 0.25:
                flags.append((MEDIUM, f"Low round-number price ratio: {round_ratio:.0%}"))

        # --- Signal 6: Identical price concentration (existing strong signal) ---
        if len(prices) >= 10:
            from collections import Counter
            price_counts = Counter(round(p, 2) for p in prices)
            top_price_pct = price_counts.most_common(1)[0][1] / len(prices)
            if top_price_pct >= 0.60:
                flags.append((HIGH, f"Identical price: {top_price_pct:.0%} of trades at same price"))
            elif top_price_pct >= 0.40:
                flags.append((MEDIUM, f"Price concentration: {top_price_pct:.0%} at same price"))

        # --- Signal 7: Win-rate CoV across markets (suspiciously uniform profitability) ---
        market_results: dict = {}
        for t in trades:
            if not t.market_id:
                continue
            if t.market_id not in market_results:
                market_results[t.market_id] = {"wins": 0, "total": 0}
            if t.is_win or t.is_loss:
                market_results[t.market_id]["total"] += 1
                if t.is_win:
                    market_results[t.market_id]["wins"] += 1
        qualified_wrs = [
            v["wins"] / v["total"]
            for v in market_results.values()
            if v["total"] >= 3
        ]
        if len(qualified_wrs) >= 5:
            mean_wr = statistics.mean(qualified_wrs)
            std_wr = statistics.stdev(qualified_wrs) if len(qualified_wrs) > 1 else 0.0
            wr_cov = std_wr / mean_wr if mean_wr > 0 else 0.0
            if wr_cov < 0.10:
                flags.append((HIGH, f"Perfectly uniform profitability: win-rate CoV={wr_cov:.3f}"))
            elif wr_cov < 0.25:
                flags.append((MEDIUM, f"Uniform profitability: win-rate CoV={wr_cov:.3f} across {len(qualified_wrs)} markets"))

        # --- Tally: 1 HIGH or 2 MEDIUM triggers bot flag ---
        high_count = sum(1 for w, _ in flags if w == HIGH)
        med_count = sum(1 for w, _ in flags if w == MEDIUM)
        triggered = high_count >= 1 or med_count >= 2

        if triggered:
            score.is_bot = True
            score.bot_flags.extend(desc for _, desc in flags)

    def _detect_farmers(self, score: WalletScore, trades: List[TradeAnalysis]):
        """Detect if wallet is farming (high volume, low profit)."""
        if score.total_trades < self.FARMER_MIN_TRADES:
            return

        if score.total_volume < self.FARMER_MIN_VOLUME:
            return

        # Very low average PnL per trade = farming (only check if PnL is actually negative/very low)
        if (
            score.avg_pnl_per_trade > -1
            and score.avg_pnl_per_trade < self.FARMER_MAX_AVG_PNL
        ):
            score.is_farmer = True
            score.farmer_flags.append(
                f"Low avg PnL: ${score.avg_pnl_per_trade:.4f} per trade"
            )

        # Very high volume but very low win rate = farming
        if score.total_volume > self.FARMER_MIN_VOLUME * 5 and score.win_rate < 30:
            score.is_farmer = True
            score.farmer_flags.append(
                f"High volume ${score.total_volume:.0f} but only {score.win_rate:.1f}% win rate"
            )

        if score.is_farmer:
            score.concerns.extend(score.farmer_flags)

    def _detect_high_loss_rate(self, score: WalletScore):
        """Detect high loss rate traders."""
        if score.loss_rate > self.HIGH_LOSS_RATE_THRESHOLD:
            score.is_high_loss_rate = True
            score.concerns.append(f"High loss rate: {score.loss_rate:.1f}%")

    def _detect_unresolved_positions(
        self, score: WalletScore, trades: List[TradeAnalysis]
    ):
        """Detect unresolved positions."""
        unresolved = [t for t in trades if not t.resolved and t.is_loss]
        score.unresolved_count = len(unresolved)
        score.unresolved_volume = sum(t.usd_value for t in unresolved)

        if score.unresolved_count > self.UNRESOLVED_THRESHOLD:
            score.has_unresolved_positions = True
            score.concerns.append(
                f"High unresolved positions: {score.unresolved_count}"
            )

    def _calculate_win_streaks(self, score: WalletScore, trades: List[TradeAnalysis]):
        """Calculate current and max win streaks."""
        if not trades:
            return

        current_streak = 0
        max_streak = 0
        recent_streak = 0

        now = trades[-1].timestamp if trades else datetime.now()
        week_ago = now - timedelta(days=7)

        for trade in reversed(trades):
            if trade.is_win:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
                if trade.timestamp and trade.timestamp >= week_ago:
                    recent_streak += 1
            else:
                current_streak = 0

        score.current_win_streak = current_streak
        score.max_win_streak = max_streak
        score.recent_win_streak = recent_streak

    def _calculate_activity_metrics(
        self, score: WalletScore, trades: List[TradeAnalysis]
    ):
        """Calculate activity-based metrics."""
        if score.days_active > 0:
            score.trades_per_day = score.total_trades / score.days_active

        # Time between trades
        if len(trades) > 1:
            times = [t.timestamp for t in trades if t.timestamp]
            if len(times) > 1:
                intervals = []
                for i in range(1, len(times)):
                    if times[i] and times[i - 1]:
                        delta = times[i] - times[i - 1]
                        intervals.append(delta.total_seconds() / 3600)  # hours
                if intervals:
                    score.avg_time_between_trades_hours = statistics.mean(intervals)

        # Trade size standard deviation
        if len(trades) > 1:
            sizes = [t.usd_value for t in trades]
            if len(sizes) > 1 and statistics.stdev(sizes) > 0:
                mean_size = statistics.mean(sizes)
                score.trade_size_std_dev = (
                    statistics.stdev(sizes) / mean_size if mean_size > 0 else 0
                )

    def _calculate_score(self, score: WalletScore) -> float:
        """Calculate overall score (0-100)."""
        score_parts = []

        # Use stored win_rate for scoring (more reliable than calculated)
        base_win_rate = (
            score.win_rate if score.win_rate > 0 else 50
        )  # Default to 50 if no data

        # Base score from win rate (40%)
        win_rate_score = base_win_rate * 0.4

        # Volume-based score (20%) - more volume = more experience
        volume_score = min(100, (score.total_volume / 10000) * 10) * 0.2

        # Activity score (15%) - more trades = more experience
        activity_score = min(100, score.total_trades / 5) * 0.15

        # Streak bonus (15%)
        streak_score = (
            min(100, score.current_win_streak * 15 + score.max_win_streak * 5) * 0.15
        )

        # Consistency/reliability (10%)
        if score.total_trades > 0:
            # Higher win rate with more trades = more reliable
            reliability = (base_win_rate * score.total_trades) / 100
            reliability_score = min(100, reliability) * 0.10
        else:
            reliability_score = 0

        # PnL bonus if available (10%)
        if score.total_pnl and score.total_pnl > 0:
            pnl_score = min(100, (score.total_pnl / 1000) * 20) * 0.10
        else:
            pnl_score = 50 * 0.10  # Neutral

        total = (
            win_rate_score
            + volume_score
            + activity_score
            + streak_score
            + reliability_score
            + pnl_score
        )

        # Penalties
        penalty = 0
        if score.is_bot:
            penalty += 30
        if score.is_farmer:
            penalty += 20
        if score.is_high_loss_rate:
            penalty += 25

        # Farming-style penalties (config-driven)
        try:
            from src.config import Config
            cfg = Config()
            farming_penalty = cfg.farming_penalty_pct
            farming_cap = cfg.farming_score_cap
            farming_min_pct = cfg.farming_avg_profit_pct_min
        except Exception:
            farming_penalty = 20
            farming_cap = 60
            farming_min_pct = 5

        # Low avg profit per win (farming-like): avg_pnl/total_volume * 100
        if score.total_volume > 0 and score.total_pnl is not None:
            avg_profit_pct = (score.total_pnl / score.total_volume) * 100
            if avg_profit_pct < farming_min_pct:
                penalty += farming_penalty

        # High volume + low ROI: likely farming
        roi_pct = (score.total_pnl / score.total_volume * 100) if (score.total_volume and score.total_pnl is not None) else 0
        if score.total_volume > 50000 and roi_pct < 5:
            penalty += 15

        # Many tiny wins: cap score
        if score.avg_pnl_per_trade < 2 and score.total_wins > 20:
            total = min(total, farming_cap)

        final_score = max(0, min(100, total - penalty))

        return final_score

    def _score_stats(self, stats: TimeWindowStats) -> float:
        """Score a time window's stats."""
        if stats.total_trades == 0:
            return 0

        # Win rate component (40%)
        win_rate_score = stats.win_rate

        # PnL component (30%)
        if stats.total_volume > 0:
            pnl_ratio = stats.total_pnl / stats.total_volume
            pnl_score = max(0, min(100, 50 + pnl_ratio * 500))  # Neutral at 10% volume
        else:
            pnl_score = 50

        # Profit factor component (20%)
        pf_score = min(100, stats.profit_factor * 50) if stats.profit_factor > 0 else 0

        # Activity component (10%) - prefer active but not excessive
        activity_score = 50
        if 1 <= stats.total_trades <= 50:
            activity_score = 100
        elif stats.total_trades > 50:
            activity_score = max(0, 100 - (stats.total_trades - 50) / 10)

        return (
            win_rate_score * 0.4
            + pnl_score * 0.3
            + pf_score * 0.2
            + activity_score * 0.1
        )

    def _determine_classification(self, score: WalletScore) -> WalletClassification:
        """Determine wallet classification based on score and flags."""
        # Hard failures
        if score.is_bot:
            return WalletClassification.BOT

        if score.is_farmer:
            return WalletClassification.FARMER

        if score.is_high_loss_rate:
            return WalletClassification.HIGH_LOSS_RATE

        # Score-based classification
        if score.total_score >= 80:
            if score.current_win_streak >= 3 or score.recent_win_streak >= 5:
                return WalletClassification.WIN_STREAK
            return WalletClassification.EXCELLENT

        if score.total_score >= 60:
            return WalletClassification.GOOD

        if score.total_score >= 40:
            return WalletClassification.AVERAGE

        return WalletClassification.INCONSISTENT

    def get_classification_reason(self, score: WalletScore) -> str:
        """Generate human-readable classification reason."""
        reasons = []

        if score.is_bot:
            return f"BOT: {'; '.join(score.bot_flags)}"

        if score.is_farmer:
            return f"FARMER: {'; '.join(score.farmer_flags)}"

        if score.is_high_loss_rate:
            return (
                f"High loss rate: {score.loss_rate:.1f}% ({score.total_losses} losses)"
            )

        # Positive reasons
        if score.current_win_streak >= 5:
            reasons.append(f"Current win streak: {score.current_win_streak}")

        if score.stats_7d and score.stats_7d.win_rate >= 60:
            reasons.append(f"7-day win rate: {score.stats_7d.win_rate:.1f}%")

        if score.stats_14d and score.stats_14d.win_rate >= 55:
            reasons.append(f"14-day win rate: {score.stats_14d.win_rate:.1f}%")

        if score.total_score >= 60:
            reasons.append(f"Overall score: {score.total_score:.0f}/100")

        if not reasons:
            if score.total_trades < self.MIN_TRADES_FOR_CLASSIFICATION:
                return f"Insufficient trades for classification ({score.total_trades} trades)"
            return f"Average performer - {score.win_rate:.1f}% win rate"

        return "; ".join(reasons)

    def _calculate_patterns(self, score: WalletScore, trades: List[TradeAnalysis]):
        """Extract trading patterns from trades."""
        from datetime import datetime

        trading_hours = {"0-6": 0, "6-12": 0, "12-18": 0, "18-24": 0}
        trading_days = {
            "mon": 0,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 0,
            "sun": 0,
        }
        odds_dist = {"low": 0, "medium": 0, "high": 0, "very_high": 0}
        category_stats = {}

        hold_durations = []
        sizes = []
        resolved_trades = []

        for trade in trades:
            if not trade.timestamp:
                continue

            hour = trade.timestamp.hour
            if 0 <= hour < 6:
                trading_hours["0-6"] += 1
            elif 6 <= hour < 12:
                trading_hours["6-12"] += 1
            elif 12 <= hour < 18:
                trading_hours["12-18"] += 1
            else:
                trading_hours["18-24"] += 1

            day = trade.timestamp.strftime("%a").lower()
            trading_days[day] += 1

            if trade.price > 0:
                if trade.price < 0.20:
                    odds_dist["low"] += 1
                elif trade.price < 0.50:
                    odds_dist["medium"] += 1
                elif trade.price < 0.80:
                    odds_dist["high"] += 1
                else:
                    odds_dist["very_high"] += 1

            sizes.append(trade.usd_value)

            if trade.category:
                if trade.category not in category_stats:
                    category_stats[trade.category] = {
                        "trades": 0,
                        "wins": 0,
                        "volume": 0.0,
                    }
                category_stats[trade.category]["trades"] += 1
                category_stats[trade.category]["volume"] += trade.usd_value
                if trade.is_win:
                    category_stats[trade.category]["wins"] += 1

            if trade.resolved:
                resolved_trades.append(trade)
                if len(resolved_trades) > 1:
                    last_ts = resolved_trades[-2].timestamp
                    if last_ts and trade.timestamp:
                        hold_durations.append(
                            (trade.timestamp - last_ts).total_seconds() / 3600
                        )

        score.trading_hours = trading_hours
        score.trading_days = trading_days
        score.odds_distribution = odds_dist
        score.category_stats = category_stats

        if hold_durations:
            score.avg_hold_duration_hours = sum(hold_durations) / len(hold_durations)

        if sizes:
            mean_size = sum(sizes) / len(sizes)
            if mean_size > 0 and len(sizes) > 1:
                import statistics

                std_dev = statistics.stdev(sizes)
                score.size_consistency = 1 - min(1.0, std_dev / mean_size)

        if sum(odds_dist.values()) > 0:
            max_odds = max(odds_dist.values())
            if max_odds == odds_dist["low"]:
                score.preferred_odds_range = "low"
            elif max_odds == odds_dist["medium"]:
                score.preferred_odds_range = "medium"
            elif max_odds == odds_dist["high"]:
                score.preferred_odds_range = "high"
            else:
                score.preferred_odds_range = "very_high"

    def _calculate_category_breakdown(self, score: WalletScore):
        """Specialty = category with most resolved wins, with PnL or local edge gate.

        Previously required wallet-wide total_pnl > 0, which failed for many real traders
        (API PnL lag, approximation mismatch). We still avoid obvious losers: require either
        positive simplified total_pnl OR a strong concentration of wins in the top category.
        """
        cat_stats = score.category_stats
        if not cat_stats:
            return

        total_pnl = score.total_pnl if score.total_pnl is not None else 0.0
        roi_pct = (
            (total_pnl / score.total_volume * 100)
            if (score.total_volume and total_pnl is not None)
            else 0.0
        )

        total_window_wins = sum(s["wins"] for s in cat_stats.values())
        if total_window_wins <= 0:
            # Many wallets have lots of open positions → 0 resolved wins in sample.
            # Still tag **primary category by volume/trades** (where they bet the most).
            by_act = sorted(
                cat_stats.items(),
                key=lambda x: (x[1]["volume"], x[1]["trades"]),
                reverse=True,
            )
            if by_act:
                cat, st = by_act[0]
                ct = int(st.get("trades") or 0)
                if ct >= 5:
                    cw = int(st.get("wins") or 0)
                    vwr = (cw / ct * 100) if ct > 0 else 0.0
                    score.specialty_category = cat
                    score.specialty_win_rate = round(vwr, 1)
                    score.specialty_volume = float(st.get("volume") or 0)
                    score.specialty_roi_pct = round(roi_pct, 1)
                    if len(by_act) > 1:
                        score.specialty_category_2 = by_act[1][0]
            return

        category_performance = {}
        for cat, stats in cat_stats.items():
            ct = stats["trades"]
            cw = stats["wins"]
            cl = ct - cw
            wr = (cw / ct * 100) if ct > 0 else 0
            category_performance[cat] = {
                "trades": ct,
                "wins": cw,
                "losses": cl,
                "win_rate": wr,
                "volume": stats["volume"],
            }

        if not category_performance:
            return

        # Top category by wins (tiebreaker: trades, then volume)
        sorted_cats = sorted(
            category_performance.items(),
            key=lambda x: (x[1]["wins"], x[1]["trades"], x[1]["volume"]),
            reverse=True,
        )
        top_cat, top_stats = sorted_cats[0]
        ct = top_stats["trades"]
        cw = top_stats["wins"]
        cl = top_stats["losses"]
        wr = top_stats["win_rate"]

        profit_gate = total_pnl > 0
        # Local edge: enough resolved activity in one category, wins beat losses, decent WR
        # Slightly relaxed vs strict desk research so dashboard specialty appears after Analyze
        local_edge_gate = (
            ct >= 4
            and cw >= 2
            and wr >= 40.0
            and cw >= cl
        )
        if not profit_gate and not local_edge_gate:
            # Volume-led label: where they trade most, even if win gate is borderline
            by_vol = sorted(
                category_performance.items(),
                key=lambda x: (x[1]["volume"], x[1]["trades"]),
                reverse=True,
            )
            if by_vol:
                vcat, vst = by_vol[0]
                vt, vw = vst["trades"], vst["wins"]
                vwr = (vw / vt * 100) if vt > 0 else 0.0
                if vt >= 6 and (vw >= 2 or vwr >= 35.0):
                    score.specialty_category = vcat
                    score.specialty_win_rate = vwr
                    score.specialty_volume = vst["volume"]
                    score.specialty_roi_pct = round(roi_pct, 1)
                    if len(sorted_cats) > 1:
                        score.specialty_category_2 = sorted_cats[1][0]
            return

        score.specialty_category = top_cat
        score.specialty_win_rate = top_stats["win_rate"]
        score.specialty_volume = top_stats["volume"]
        score.specialty_roi_pct = round(roi_pct, 1)
        if len(sorted_cats) > 1:
            score.specialty_category_2 = sorted_cats[1][0]

    def _determine_tier(self, score: WalletScore) -> str:
        """Determine tier based on score and flags."""
        if score.is_bot or score.is_farmer:
            return "watch"

        if score.total_score >= 80 and score.current_win_streak >= 5:
            return "elite"

        if score.total_score >= 50 and not score.is_high_loss_rate:
            return "vetted"

        return "watch"

    def _calculate_volume_weighted_win_rate(
        self, score: WalletScore, trades: List[TradeAnalysis]
    ):
        """Calculate volume-weighted win rate."""
        total_winning_volume = 0.0
        total_volume = 0.0

        for trade in trades:
            total_volume += trade.usd_value
            if trade.is_win:
                total_winning_volume += trade.usd_value

        if total_volume > 0:
            score.volume_weighted_win_rate = (total_winning_volume / total_volume) * 100

    def _calculate_consecutive_losses(
        self, score: WalletScore, trades: List[TradeAnalysis]
    ):
        """Calculate consecutive loss streak."""
        if not trades:
            return

        resolved = [t for t in trades if t.resolved]
        if not resolved:
            return

        current_loss_streak = 0
        max_loss_streak = 0

        for trade in resolved:
            if trade.is_loss:
                current_loss_streak += 1
                max_loss_streak = max(max_loss_streak, current_loss_streak)
            else:
                current_loss_streak = 0

        score.consecutive_losses = current_loss_streak
        score.max_consecutive_losses = max_loss_streak


def classify_wallet_batch(
    addresses: List[str], trades_map: Dict[str, List[Dict]], api_client=None
) -> Dict[str, WalletScore]:
    """Classify multiple wallets."""
    classifier = WalletClassifier(api_client)
    results = {}

    for address in addresses:
        trades = trades_map.get(address, [])
        score = classifier.classify_wallet(address, trades)
        results[address] = score

    return results
