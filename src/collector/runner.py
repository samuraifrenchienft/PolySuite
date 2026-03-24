"""Background market data collector.

Runs in a daemon thread, periodically collects:
- Wallet stats (total_trades, wins, win_rate, volume) — updates dashboard metrics
- Insider/Whale signals
- Convergence (2+ high-performers in same market)
- Contrarian opportunities
- Active markets (for alert tracking)

Results are cached so dashboard scan buttons return data immediately.
Wallet stats are written to storage so dashboard header metrics stay current.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def _wallet_last_updated_ts(w) -> Optional[float]:
    """Parse wallet.last_updated (ISO) to unix time; None if missing or invalid."""
    lu = getattr(w, "last_updated", None)
    if not lu:
        return None
    try:
        s = str(lu).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError, OSError):
        return None


def _wallet_stats_staleness_key(w):
    """Sort: never updated first, then oldest last_updated first."""
    ts = _wallet_last_updated_ts(w)
    addr = (getattr(w, "address", "") or "").lower()
    if ts is None:
        return (0, 0.0, addr)
    return (1, ts, addr)


def _dedupe_trader_rows(traders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stable de-dupe by normalized 0x address (Data API + Gamma may overlap)."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for t in traders or []:
        a = (t.get("address") or t.get("proxyWallet") or "").strip().lower()
        if not a or not a.startswith("0x") or a in seen:
            continue
        seen.add(a)
        row = dict(t)
        row["address"] = a
        out.append(row)
    return out


def run_wallet_discovery_step(
    storage,
    config,
    api_factory,
    last_ts_ref: List[float],
    offset_ref: Optional[List[int]] = None,
    category_idx_ref: Optional[List[int]] = None,
) -> int:
    """Auto-add Polymarket leaderboard wallets when under cap.

    Rotates through the leaderboard by advancing ``offset_ref`` each run so we
    discover wallets ranked 0–N on run 1, N–2N on run 2, etc. Resets when it
    reaches ``wallet_discovery_rotate_depth``. Also cycles through configured
    categories (OVERALL, CRYPTO, POLITICS, SPORTS…) so specialists from each
    pool are discovered over time.

    Returns number of wallets added this invocation (0 if skipped or error).
    """
    if not last_ts_ref:
        last_ts_ref.append(0.0)
    if offset_ref is None:
        offset_ref = [0]
    if category_idx_ref is None:
        category_idx_ref = [0]

    if not config.get("wallet_discovery_enabled", True):
        return 0
    interval = int(config.get("wallet_discovery_interval_sec", 1800) or 1800)
    now = time.time()
    if now - last_ts_ref[0] < interval:
        return 0

    max_new = int(config.get("wallet_discovery_max_new", 15) or 15)
    max_wallets = int(config.get("wallet_discovery_max_wallets", 250) or 250)
    rotate_depth = int(config.get("wallet_discovery_rotate_depth", 500) or 500)
    fetch_limit = int(config.get("wallet_discovery_fetch_limit", 150) or 150)
    min_pnl = float(config.get("wallet_discovery_min_pnl", 0) or 0)

    # Which categories to cycle through
    from src.market.leaderboard import LeaderboardImporter as _LI
    all_cats = config.get("wallet_discovery_categories") or ["OVERALL", "CRYPTO", "POLITICS", "SPORTS"]
    if isinstance(all_cats, str):
        all_cats = [c.strip() for c in all_cats.split(",") if c.strip()]
    # Pick category for this run and advance index
    cat_idx = category_idx_ref[0] % len(all_cats)
    categories = [all_cats[cat_idx]]
    category_idx_ref[0] = (cat_idx + 1) % len(all_cats)

    # Current offset into leaderboard
    current_offset = offset_ref[0]

    added = 0
    try:
        from src.wallet import Wallet
        from src.utils import is_valid_address

        wallets = storage.list_wallets()
        if len(wallets) >= max_wallets:
            logger.info(
                "[Discovery] At wallet cap (%d/%d); not adding.",
                len(wallets), max_wallets,
            )
            return 0

        importer = _LI(api_factory)
        traders = importer.fetch_polymarket_leaderboard_only(
            limit=fetch_limit,
            start_offset=current_offset,
            categories=categories,
        )

        # Advance offset for next run; reset when we've covered rotate_depth
        next_offset = current_offset + fetch_limit
        offset_ref[0] = 0 if next_offset >= rotate_depth else next_offset
        if next_offset >= rotate_depth:
            logger.info("[Discovery] Offset rotated back to 0 after reaching depth %d", rotate_depth)

        if config.get("wallet_discovery_gamma_supplement", True):
            extra = importer.fetch_gamma_leaderboard_wallets(limit=100)
            seen_addr = {
                (t.get("address") or "").strip().lower()
                for t in traders
                if (t.get("address") or "").strip().lower().startswith("0x")
            }
            for t in extra:
                a = (t.get("address") or "").strip().lower()
                if a and a.startswith("0x") and a not in seen_addr:
                    seen_addr.add(a)
                    traders.append(t)

        traders = _dedupe_trader_rows(traders)
        if not traders:
            logger.warning(
                "[Discovery] Polymarket leaderboard returned no 0x rows; "
                "will retry on next poll (interval not advanced)"
            )
            return 0

        # Min volume filter
        min_vol = float(config.get("wallet_discovery_min_volume", 0) or 0)
        if min_vol > 0:
            before = len(traders)
            traders = [t for t in traders if (t.get("volume") is None or float(t.get("volume") or 0) >= min_vol)]
            if before > len(traders):
                logger.info("[Discovery] Filtered by min_volume %.0f: %d -> %d", min_vol, before, len(traders))

        # Min PnL filter — skip low-PnL wallets at intake
        if min_pnl > 0:
            before = len(traders)
            traders = [t for t in traders if (t.get("pnl") is None or float(t.get("pnl") or 0) >= min_pnl)]
            if before > len(traders):
                logger.info("[Discovery] Filtered by min_pnl %.0f: %d -> %d", min_pnl, before, len(traders))

        blocklist = {
            a.strip().lower()
            for a in (config.get("wallet_blocklist") or [])
            if isinstance(a, str) and a.strip()
        }

        last_ts_ref[0] = now
        for i, t in enumerate(traders or [], 1):
            if added >= max_new:
                break
            if len(storage.list_wallets()) >= max_wallets:
                break
            addr = (t.get("address") or t.get("proxyWallet") or t.get("ownerPubkey") or "").strip()
            if not addr or not addr.startswith("0x") or not is_valid_address(addr):
                continue
            addr = addr.lower()
            if addr in blocklist:
                logger.debug("[Discovery] Skipped blocklisted wallet %s", addr[:16] + "...")
                continue
            if storage.get_wallet(addr):
                continue
            nick = t.get("username") or t.get("user") or t.get("name") or f"Trader{i}"
            w = Wallet(address=addr, nickname=str(nick)[:32])
            if storage.add_wallet(w):
                added += 1
                logger.info(
                    "[Discovery] Added wallet %s (%s) [%s offset=%d]",
                    addr[:16] + "...", nick[:20], categories[0], current_offset,
                )
                time.sleep(0.2)

        if added:
            logger.info("[Discovery] Wallet discovery: added %d new wallet(s)", added)
        elif traders and not added:
            logger.debug(
                "[Discovery] No new addresses added (all %d leaderboard wallets already tracked)",
                len(traders),
            )
    except Exception as e:
        logger.warning("[Discovery] wallet_discovery: %s", e)
    return added


def run_wallet_cleanup_step(storage, config, last_ts_ref: List[float]) -> int:
    """Remove useless wallets: 0 trades, 0 wins, low win rate, bot/farmer.

    ``last_ts_ref`` is a one-element list [last_run_unix_time]. Runs when
    ``wallet_cleanup_enabled`` and interval elapsed. Returns number removed.
    """
    if not last_ts_ref:
        last_ts_ref.append(0.0)
    if not config.get("wallet_cleanup_enabled", True):
        return 0
    interval = int(config.get("wallet_cleanup_interval_sec", 3600) or 3600)
    now = time.time()
    if now - last_ts_ref[0] < interval:
        return 0
    last_ts_ref[0] = now
    # Only remove truly bottom-tier: 0 trades, confirmed bots, farmers, terrible win rate.
    # Wallets with decent win rates stay regardless of vet tier — just labelled accordingly.
    min_win_rate = float(config.get("wallet_cleanup_min_win_rate", 40) or 40)
    min_trades = int(config.get("wallet_cleanup_min_trades", 5) or 0)
    grace_days = int(config.get("wallet_cleanup_grace_days", 7) or 7)
    remove_farmer = config.get("wallet_cleanup_remove_farmer", True)
    remove_bot = config.get("wallet_cleanup_remove_bot", True)
    bot_min_score = int(config.get("wallet_cleanup_bot_min_bot_score", 90) or 90)
    removed = 0
    try:
        from datetime import datetime, timedelta
        wallets = storage.list_wallets()
        if not wallets:
            return 0
        cutoff = datetime.utcnow() - timedelta(days=grace_days)
        for w in wallets:
            try:
                created_at = getattr(w, "created_at", None)
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        else:
                            created = created_at
                        created_naive = created.replace(tzinfo=None) if getattr(created, "tzinfo", None) else created
                        if created_naive > cutoff:
                            continue
                    except (ValueError, TypeError, AttributeError):
                        pass
                trades = int(w.total_trades or 0)
                wins = int(getattr(w, "wins", 0) or 0)
                win_rate = float(w.win_rate or 0)
                is_bot = getattr(w, "is_bot", False) or False
                is_farmer = getattr(w, "is_farmer", False) or False
                bot_score = getattr(w, "bot_score", None)
                # Farmer removal: classifier flag is sufficient (high-vol / low-profit pattern)
                if remove_farmer and is_farmer:
                    storage.remove_wallet(w.address)
                    removed += 1
                    logger.info("[Cleanup] Removed %s (farmer)", w.address[:16] + "...")
                    continue
                # Bot removal: require vet-confirmed high bot_score to avoid false positives
                # from the classifier alone. If bot_score is NULL (never vetted) skip removal.
                if remove_bot and is_bot:
                    if bot_score is not None and bot_score >= bot_min_score:
                        storage.remove_wallet(w.address)
                        removed += 1
                        logger.info(
                            "[Cleanup] Removed %s (bot, score=%d >= %d)",
                            w.address[:16] + "...", bot_score, bot_min_score,
                        )
                        continue
                    else:
                        logger.debug(
                            "[Cleanup] Skipped %s (is_bot but bot_score=%s < threshold %d; keeping)",
                            w.address[:16] + "...", bot_score, bot_min_score,
                        )
                if trades == 0:
                    storage.remove_wallet(w.address)
                    removed += 1
                    logger.info("[Cleanup] Removed %s (0 trades, inactive)", w.address[:16] + "...")
                    continue
                # Below min_trades: keep (stats too thin to judge vs. configured zones)
                if min_trades > 0 and trades < min_trades:
                    continue
                # Only remove 0-win wallets with enough trades to be sure (not thin data)
                if wins == 0 and trades >= 20:
                    storage.remove_wallet(w.address)
                    removed += 1
                    logger.info("[Cleanup] Removed %s (0 wins across %d trades)", w.address[:16] + "...", trades)
                    continue
                # Only remove truly terrible win rates — decent performers stay regardless of vet tier
                if trades >= min_trades and win_rate < min_win_rate:
                    storage.remove_wallet(w.address)
                    removed += 1
                    logger.info("[Cleanup] Removed %s (win_rate %.1f%% < %s%%)", w.address[:16] + "...", win_rate, min_win_rate)
            except Exception as e:
                logger.debug("[Cleanup] wallet %s: %s", w.address[:12], e)
        if removed:
            logger.info("[Cleanup] Removed %d useless wallet(s)", removed)
    except Exception as e:
        logger.warning("[Cleanup] %s", e)
    return removed


# Cache entry: {"data": {...}, "ts": float, "ok": bool}
DEFAULT_SCAN_INTERVAL = 1800  # 30 min (1-2x/hr)
DEFAULT_CACHE_TTL = 600  # 10 min


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(val) if val is not None else lo))


class MarketDataCollector:
    """Background collector for market/signal data. Thread-safe cache."""

    def __init__(
        self,
        storage,
        config,
        api_factory,
        interval_sec: int = None,
        cache_ttl_sec: int = None,
    ):
        self.storage = storage
        self.config = config
        self.api_factory = api_factory
        self.interval_sec = interval_sec if interval_sec is not None else _clamp(
            config.get("scan_interval_sec", DEFAULT_SCAN_INTERVAL), 30, 3600
        )
        raw_ttl = cache_ttl_sec if cache_ttl_sec is not None else config.get("cache_ttl_sec", DEFAULT_CACHE_TTL)
        self.cache_ttl_sec = _clamp(int(raw_ttl or 0), 0, 3600)  # 0 = always bypass cache
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._dispatcher = None
        self._telegram = None
        self._alerts_log: list = []
        self._alerts_log_max = 100
        self._scan_results_storage = None
        self._discovery_ts_ref: List[float] = [0.0]
        self._discovery_offset_ref: List[int] = [0]   # rotates through leaderboard depth
        self._discovery_cat_idx_ref: List[int] = [0]  # cycles through categories
        self._last_cleanup_ts_ref: List[float] = [0.0]
        # Round-robin offset when wallet_stats_max_per_cycle < number of wallets
        self._wallet_stats_offset = 0

    def _persist_scan_result(self, scan_type: str, count: int, payload: dict):
        """Persist scan result for analytics (lazy-init storage)."""
        try:
            if self._scan_results_storage is None:
                from src.analytics.scan_results_storage import ScanResultsStorage
                self._scan_results_storage = ScanResultsStorage()
            self._scan_results_storage.save(scan_type, time.time(), count, payload)
        except Exception as e:
            logger.debug("[Collector] persist scan_result: %s", e)

    def _log_alert(self, alert_type: str, data: dict):
        """Append to recent alerts for dashboard display."""
        entry = {"type": alert_type, "ts": time.time(), "data": {}}
        if alert_type == "insider":
            wt = data.get("winning_trade") or {}
            addr = data.get("address", "")
            market_id = wt.get("market_id", "")
            entry["data"] = {
                "address": addr[:16] + "..." if len(addr) > 16 else addr,
                "question": (wt.get("question") or "Unknown")[:100],
                "confidence": data.get("confidence", "?"),
                "trade_size": data.get("trade_size", 0),
                "side": (wt.get("side") or "?").upper(),
                "pnl": round(wt.get("pnl", 0), 2),
                "profile_link": f"https://polymarket.com/profile/{addr}" if addr else "",
                "market_link": f"https://polymarket.com/market/{market_id}" if market_id else "",
            }
        elif alert_type == "convergence":
            m = data.get("market_info") or {}
            market_id = data.get("market_id", "")
            entry["data"] = {
                "question": (m.get("question") or "Unknown")[:100],
                "wallet_count": data.get("wallet_count", 0),
                "market_id": market_id,
                "market_link": f"https://polymarket.com/market/{market_id}" if market_id else "",
            }
        with self._lock:
            self._alerts_log.append(entry)
            if len(self._alerts_log) > self._alerts_log_max:
                self._alerts_log.pop(0)

    def get_recent_alerts(self, limit: int = 50) -> list:
        """Get recent alerts for dashboard (newest first)."""
        with self._lock:
            out = list(self._alerts_log[-limit:])
        return sorted(out, key=lambda x: x["ts"], reverse=True)

    def _get_dispatcher(self):
        """Lazy-init Discord dispatcher."""
        if self._dispatcher is None and self.config.get("discord_webhook_url"):
            from src.alerts import AlertDispatcher
            self._dispatcher = AlertDispatcher(
                self.config.get("discord_webhook_url", ""),
                cooldown_seconds=int(self.config.get("alert_cooldown", 300) or 300),
            )
        return self._dispatcher

    def _get_telegram(self):
        """Lazy-init Telegram dispatcher."""
        if self._telegram is None and self.config.get("telegram_bot_token") and self.config.get("telegram_chat_id"):
            from src.alerts.telegram import TelegramDispatcher
            self._telegram = TelegramDispatcher(
                self.config.get("telegram_bot_token", ""),
                self.config.get("telegram_chat_id", ""),
            )
        return self._telegram

    def start(self):
        """Start background collection thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Collector] Started, interval=%ds", self.interval_sec)

    def stop(self):
        """Stop background collection."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[Collector] Stopped")

    def _run_loop(self):
        """Main collection loop."""
        # Run once immediately
        self._collect_all()
        while not self._stop.wait(timeout=self.interval_sec):
            self._collect_all()

    def _collect_all(self):
        """Run all collectors and update cache."""
        # Order: discovery → stats → cleanup. Stats MUST run before cleanup so we
        # don't remove wallets that simply haven't been refreshed yet (0/0/0 stale).
        self._collect_wallet_discovery()
        self._collect_wallet_stats()
        self._collect_wallet_cleanup()
        self._collect_insider()
        self._collect_convergence()
        self._collect_contrarian()
        self._collect_active_markets()

    def _collect_wallet_discovery(self):
        """Add new wallets from leaderboard when under limit."""
        run_wallet_discovery_step(
            self.storage, self.config, self.api_factory, self._discovery_ts_ref,
            offset_ref=self._discovery_offset_ref,
            category_idx_ref=self._discovery_cat_idx_ref,
        )

    def _collect_wallet_cleanup(self):
        """Remove useless wallets automatically (delegates to run_wallet_cleanup_step)."""
        run_wallet_cleanup_step(self.storage, self.config, self._last_cleanup_ts_ref)

    def _collect_wallet_stats(self):
        """Refresh wallet stats from Polymarket so dashboard metrics stay current."""
        try:
            from src.wallet.calculator import WalletCalculator
            wallets = self.storage.list_wallets()
            if not wallets:
                return
            skip_h = float(self.config.get("collector_stats_skip_hours", 0) or 0)
            cutoff = time.time() - skip_h * 3600
            eligible: List = []
            for w in wallets:
                ts = _wallet_last_updated_ts(w)
                if skip_h <= 0:
                    eligible.append(w)
                elif ts is None:
                    eligible.append(w)
                elif ts < cutoff:
                    eligible.append(w)
            if not eligible:
                logger.debug(
                    "[Collector] wallet stats: all %d wallet(s) within skip window (%.0fh)",
                    len(wallets),
                    skip_h,
                )
                return
            eligible.sort(key=_wallet_stats_staleness_key)
            n = len(eligible)
            max_per = int(self.config.get("wallet_stats_max_per_cycle", 0) or 0)
            if max_per <= 0 or max_per >= n:
                to_process = eligible
            else:
                start = self._wallet_stats_offset % n
                to_process = [eligible[(start + i) % n] for i in range(max_per)]
                self._wallet_stats_offset = (start + max_per) % n
            calculator = WalletCalculator(self.api_factory)
            updated = 0
            for wallet in to_process:
                try:
                    (
                        total_trades,
                        wins,
                        win_rate,
                        total_volume,
                        _resolved_n,
                    ) = calculator.calculate_wallet_stats(wallet.address)
                    self.storage.update_wallet_stats(
                        wallet.address,
                        total_trades,
                        wins,
                        total_volume,
                        win_rate=win_rate,
                    )
                    updated += 1
                    time.sleep(0.3)
                except Exception as e:
                    logger.debug("[Collector] wallet %s: %s", wallet.address[:12], e)
            if updated:
                tracked = len(wallets)
                if len(to_process) < len(eligible) or len(eligible) < tracked:
                    logger.info(
                        "[Collector] Refreshed %d wallet(s) this cycle (%d/%d eligible of %d tracked)",
                        updated,
                        len(to_process),
                        len(eligible),
                        tracked,
                    )
                else:
                    logger.info("[Collector] Refreshed %d/%d wallet stats", updated, len(eligible))
        except Exception as e:
            logger.warning("[Collector] wallet_stats: %s", e)

    def _collect_insider(self):
        try:
            from src.core.detector_factory import DetectorFactory
            factory = DetectorFactory(self.config, self.storage, self.api_factory)
            detector = factory.get_insider_detector()
            signals = detector.scan_for_signals(limit=10)
            out = []
            alerts_on = self.config.get("alerts_enabled", True) and self.config.get("insider_alerts", True)
            min_pnl = float(self.config.get("alert_min_pnl", 500) or 500)
            skip_low = self.config.get("alert_skip_low_confidence", True)
            for s in signals:
                # Noise filters: skip LOW confidence and low PnL
                wt = s.get("winning_trade") or {}
                pnl = float(wt.get("pnl", 0) or 0)
                conf = (s.get("confidence") or "LOW").upper()
                if skip_low and conf == "LOW":
                    continue
                if pnl < min_pnl:
                    continue
                if alerts_on:
                    disp = self._get_dispatcher()
                    tg = self._get_telegram()
                    sent = False
                    if disp and disp.send_insider_alert(s):
                        sent = True
                    if tg and tg.is_configured() and tg.send_insider_alert(s):
                        sent = True
                    if sent:
                        self._log_alert("insider", s)
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
            with self._lock:
                ts = time.time()
                self._cache["insider"] = {"ok": True, "signals": out, "count": len(out), "ts": ts}
            self._persist_scan_result("insider", len(out), {"signals": out})
        except Exception as e:
            logger.warning("[Collector] insider: %s", e)
            with self._lock:
                self._cache["insider"] = {"ok": False, "error": str(e), "signals": [], "count": 0, "ts": time.time()}

    def _collect_convergence(self):
        try:
            from src.core.detector_factory import DetectorFactory
            factory = DetectorFactory(self.config, self.storage, self.api_factory)
            detector = factory.get_convergence_detector()
            convergences = detector.find_convergences(min_wallets=2)
            out = []
            alerts_on = self.config.get("alerts_enabled", True) and self.config.get("convergence_alerts", True)
            threshold = float(self.config.get("win_rate_threshold", 55) or 55)
            for c in convergences:
                if alerts_on:
                    m = c.get("market_info") or {}
                    disp = self._get_dispatcher()
                    tg = self._get_telegram()
                    sent = False
                    if disp and disp.send_convergence_alert(m, c.get("wallets", []), threshold):
                        sent = True
                    if tg and tg.is_configured() and tg.send_convergence_alert(m, c.get("wallets", []), threshold):
                        sent = True
                    if sent:
                        self._log_alert("convergence", c)
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
            with self._lock:
                ts = time.time()
                self._cache["convergence"] = {"ok": True, "convergences": out, "count": len(out), "ts": ts}
            self._persist_scan_result("convergence", len(out), {"convergences": out})
        except Exception as e:
            logger.warning("[Collector] convergence: %s", e)
            with self._lock:
                self._cache["convergence"] = {"ok": False, "error": str(e), "convergences": [], "count": 0, "ts": time.time()}

    def _collect_contrarian(self):
        try:
            from src.core.detector_factory import DetectorFactory
            factory = DetectorFactory(self.config, self.storage, self.api_factory)
            detector = factory.get_contrarian_detector()
            signals = detector.scan()
            out = []
            for s in signals:
                out.append({
                    "market_id": s.get("market_id"),
                    "question": s.get("question", "Unknown")[:120],
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
            with self._lock:
                ts = time.time()
                self._cache["contrarian"] = {"ok": True, "signals": out, "count": len(out), "ts": ts}
            self._persist_scan_result("contrarian", len(out), {"signals": out})
        except Exception as e:
            logger.warning("[Collector] contrarian: %s", e)
            with self._lock:
                self._cache["contrarian"] = {"ok": False, "error": str(e), "signals": [], "count": 0, "ts": time.time()}

    def _collect_active_markets(self):
        """Cache active markets for alert tracking."""
        try:
            polymarket = self.api_factory.get_polymarket_api()
            markets = polymarket.get_active_markets(limit=100) or []
            out = [{"id": m.get("id"), "question": (m.get("question") or "Unknown")[:80], "volume": m.get("volume", 0)} for m in markets if m.get("id")]
            with self._lock:
                self._cache["active_markets"] = {"ok": True, "markets": out, "count": len(out), "ts": time.time()}
        except Exception as e:
            logger.warning("[Collector] active_markets: %s", e)
            with self._lock:
                self._cache["active_markets"] = {"ok": False, "error": str(e), "markets": [], "count": 0, "ts": time.time()}

    def get_cached(self, key: str, force_fresh: bool = False) -> Optional[Dict[str, Any]]:
        """Get cached result if fresh. Returns None if stale, missing, or cache_ttl_sec=0."""
        if force_fresh or self.cache_ttl_sec <= 0:
            return None
        with self._lock:
            entry = self._cache.get(key)
        if not entry:
            return None
        ts = entry.get("ts", 0)
        if time.time() - ts > self.cache_ttl_sec:
            return None
        return entry
