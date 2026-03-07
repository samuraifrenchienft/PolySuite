"""Main entry point for PolySuite CLI."""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask_socketio import SocketIO

from src.alerts import AlertDispatcher
from src.alerts.convergence import ConvergenceDetector
from src.alerts.odds import OddsAlerter
from src.alerts.position import PositionAlerter
from src.alerts.telegram import TelegramDispatcher
from src.analytics.smart_money import SmartMoneyDetector
from src.config import Config
from src.dashboard.app import Dashboard
from src.discord_bot import DiscordBot
from src.market.api import APIClientFactory
from src.market.discovery import MarketDiscovery
from src.market.leaderboard import LeaderboardImporter
from src.market.aggregator import aggregator
from src.tasks import TaskManager
from src.telegram_bot import TelegramBot
from src.wallet import Wallet
from src.utils import sanitize_nickname
from src.wallet.calculator import WalletCalculator
from src.wallet.storage import WalletStorage
from src.ai.engine import ai_filter
from src.alerts.formatter import formatter
from src.alerts.trendscanner import trendscanner
from src.wallet.vetting import WalletVetting
from src.alerts.events import EventAlerter
from src.alerts.combined import CombinedDispatcher
from src.alerts.liquidity import check_liquidity_depth
from src.alerts.qualifier import Qualifier
from backtest.storage import BacktestStorage


def add_wallet(args, storage: WalletStorage, _config: Config):
    """Add a new wallet to track."""
    # Check max wallets
    wallets = storage.list_wallets()
    if len(wallets) >= 10:
        print("Maximum 10 wallets allowed. Remove one first.")
        return

    try:
        nickname = sanitize_nickname(args.nickname.strip()) or args.address[:12] + "..."
        wallet = Wallet(address=args.address.strip(), nickname=nickname)
        storage.add_wallet(wallet)
        print(f"Added wallet {args.nickname} ({args.address})")
    except sqlite3.IntegrityError:
        print(f"Wallet with address {args.address} already exists.")


def remove_wallet(args, storage: WalletStorage, _config: Config):
    """Remove a wallet from tracking."""
    address = args.address.strip()

    if storage.remove_wallet(address):
        print(f"[-] Removed wallet: {address[:10]}...")
    else:
        print(f"[-] Wallet not found: {address}")


def list_wallets(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """List all tracked wallets."""
    wallets = storage.list_wallets(
        min_trades=args.min_trades, min_volume=args.min_volume
    )

    if args.min_recent_trades is not None:
        calculator = WalletCalculator(api_factory)
        wallets = [
            w
            for w in wallets
            if calculator.count_recent_trades(w.address, args.recent_days)
            >= args.min_recent_trades
        ]

    if not wallets:
        print("No wallets found matching the specified criteria.")
        return

    print(
        f"{'Nickname':<20} {'Address':<45} {'Trades':<10} {'Wins':<10} {'Win Rate':<15} {'Volume':<15} {'Status'}"
    )
    for w in wallets:
        threshold = config.win_rate_threshold
        status = "*HIGH*" if w.is_high_performer(threshold) else ""
        print(
            f"{w.nickname:<20} {w.address:<45} {w.total_trades:<10} {w.wins:<10} {w.win_rate:<15.2f} ${w.trade_volume:<14} {status}"
        )


def refresh_wallet(
    args, storage: WalletStorage, _config: Config, api_factory: APIClientFactory
):
    """Refresh wallet stats from Polymarket."""
    address = args.address.strip()

    wallet = storage.get_wallet(address)
    if not wallet:
        print(f"[-] Wallet not found: {address}")
        return

    print(f"Refreshing {wallet.nickname}...")

    calculator = WalletCalculator(api_factory)
    total_trades, wins, win_rate, total_volume = calculator.calculate_wallet_stats(
        address
    )

    if total_trades > 0:
        storage.update_wallet_stats(address, total_trades, wins, total_volume)
        storage.log_wallet_history(wallet)
        print(f"[+] Updated: {win_rate:.1f}% win rate ({wins}/{total_trades} trades)")
    else:
        print("[-] No trades found for this wallet")


def refresh_all(
    _args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Refresh all wallet stats."""
    wallets = storage.list_wallets()

    if not wallets:
        print("No wallets to refresh")
        return

    print(f"Refreshing {len(wallets)} wallets...")

    calculator = WalletCalculator(api_factory)

    for wallet in wallets:
        total_trades, wins, win_rate, total_volume = calculator.calculate_wallet_stats(
            wallet.address
        )
        if total_trades > 0:
            storage.update_wallet_stats(
                wallet.address, total_trades, wins, total_volume
            )
            storage.log_wallet_history(wallet)
            print(f"[+] {wallet.nickname}: {win_rate:.1f}% ({wins}/{total_trades})")
        else:
            print(f"- {wallet.nickname}: No trades")

    print("\n[+] All wallets refreshed")


def _dispatch_market_alerts(
    markets,
    min_volume,
    top_n,
    ai_filter,
    formatter_fn,
    combined,
    category,
    source_label,
    use_market_category=False,
    backtest_storage=None,
):
    """Helper: qualify, AI analyze, format, dispatch for Kalshi/Jupiter-style markets."""
    passed = sorted(
        [m for m in markets if float(getattr(m, "volume", 0) or 0) >= min_volume],
        key=lambda x: float(getattr(x, "volume", 0) or 0),
        reverse=True,
    )[:top_n]
    for m in passed:
        entry_zone, conviction, entry_reason = "", "", ""
        try:
            q = getattr(m, "question", "Unknown")
            vol = float(getattr(m, "volume", 0) or 0)
            price = float(getattr(m, "price", 0.5) or 0.5)
            market_dict = {
                "question": q,
                "volume": vol,
                "outcomePrices": [price, 1 - price],
            }
            zones = ai_filter.analyze_entry_zones([market_dict])
            if zones:
                z = zones[0]
                entry_zone = z.get("entry_zone", "")
                conviction = z.get("confidence", "")
                entry_reason = (z.get("reason", "") or "")[:100]
        except Exception:
            pass
        msg = formatter_fn(
            m, entry_zone=entry_zone, conviction=conviction, entry_reason=entry_reason
        )
        dispatch_category = (
            getattr(m, "category", "") or category if use_market_category else category
        )
        combined.send_to_alerts(msg, category=dispatch_category)
        try:
            if backtest_storage and entry_zone in ("BUY_YES", "BUY_NO"):
                market_id = getattr(m, "id", None) or getattr(m, "conditionId", None)
                if market_id:
                    side = "YES" if entry_zone == "BUY_YES" else "NO"
                    backtest_storage.log_suggestion(
                        source=(source_label or "market").lower(),
                        category=dispatch_category or category or "other",
                        market_id=str(market_id),
                        question=getattr(m, "question", ""),
                        side=side,
                        entry_price=float(getattr(m, "price", 0.5) or 0.5),
                        conviction=conviction,
                        entry_reason=entry_reason,
                    )
        except Exception:
            pass
        print(f"   {source_label}: {getattr(m, 'question', '')[:40]}...")


def _record_actionable_suggestion(
    backtest_storage,
    market: dict,
    entry_zone: str,
    category: str,
    source: str,
    conviction: str = "",
    entry_reason: str = "",
):
    """Persist actionable recommendation (BUY_YES/BUY_NO) for outcome tracking."""
    if not backtest_storage or entry_zone not in ("BUY_YES", "BUY_NO"):
        return
    market_id = market.get("id") or market.get("conditionId")
    if not market_id:
        return
    yes_price = market.get("yes_pct")
    if yes_price is None:
        raw_prices = market.get("outcomePrices")
        try:
            prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
            if prices and len(prices) >= 1:
                yes_price = float(prices[0])
        except Exception:
            yes_price = None
    backtest_storage.log_suggestion(
        source=(source or "market").lower(),
        category=(category or "other").lower(),
        market_id=str(market_id),
        question=market.get("question", ""),
        side="YES" if entry_zone == "BUY_YES" else "NO",
        entry_price=float(yes_price) if yes_price is not None else None,
        conviction=conviction,
        entry_reason=(entry_reason or "")[:120],
    )


def _format_weekly_suggestion_report(summary: dict, days: int, stake_usd: float) -> str:
    """Format weekly AI suggestion performance report."""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "📈 **AI SUGGESTION WEEKLY SCORECARD**",
        f"_{days}d window | ${stake_usd:.0f} per suggestion_",
        "",
        f"Signals: {summary.get('total', 0)} | Resolved: {summary.get('resolved', 0)} | Open: {summary.get('open', 0)}",
        f"Accuracy: {summary.get('accuracy_pct', 0):.1f}% ({summary.get('wins', 0)}W / {summary.get('losses', 0)}L)",
        f"Sim P&L: ${summary.get('pnl_usd', 0):,.2f}",
    ]
    by_cat = summary.get("by_category") or []
    if by_cat:
        lines.append("")
        lines.append("By category:")
        for c in by_cat[:6]:
            lines.append(
                f"• {c.get('category', 'other')}: {c.get('total', 0)} sig | {c.get('wins', 0)}W/{c.get('losses', 0)}L | ${c.get('pnl_usd', 0):,.0f}"
            )
    return "\n".join(lines)


def _generate_ai_market_report(polymarket_api, combined, config):
    """Generates and sends an AI market report."""
    if not config.ai_report_enabled or not ai_filter.is_available():
        return
    print("\n[*] Generating AI market report...")
    try:
        # Fetch fresh markets (sort by volume client-side)
        all_markets = polymarket_api.get_markets(limit=200, active=True) or []
        all_markets.sort(key=lambda x: float(x.get("volume", 0) or 0), reverse=True)
        min_gross_return_pct = float(
            config.get("ai_report_min_gross_return_pct", 8.0) or 8.0
        )
        max_easy_side_price = float(
            config.get("ai_report_max_easy_side_price", 0.92) or 0.92
        )
        min_easy_side_price = float(
            config.get("ai_report_min_easy_side_price", 0.55) or 0.55
        )

        # Get prices for analysis
        scored = []
        for m in all_markets:
            v = float(m.get("volume", 0) or 0)
            if v < 50000:  # Skip low volume
                continue

            # Get odds
            prices = m.get("outcomePrices", "")
            odds_info = {}
            if prices:
                try:
                    p = json.loads(prices) if isinstance(prices, str) else prices
                    if p and len(p) >= 2:
                        yes_odds = float(p[0])
                        no_odds = float(p[1])
                        odds_info = {
                            "yes": yes_odds,
                            "no": no_odds,
                            "spread": abs((yes_odds + no_odds) - 1.0),
                        }
                        # Keep "easy win with room" only:
                        # high implied probability but not so extreme that upside is negligible.
                        easy_side_price = max(yes_odds, no_odds)
                        gross_return_pct = ((1.0 / easy_side_price) - 1.0) * 100.0
                        if (
                            easy_side_price > max_easy_side_price
                            or easy_side_price < min_easy_side_price
                            or gross_return_pct < min_gross_return_pct
                        ):
                            continue
                except Exception:
                    pass

            # AI analyze
            analysis = ai_filter.analyze_new_market(m)

            scored.append(
                {
                    "market": m,
                    "volume": v,
                    "odds": odds_info,
                    "analysis": analysis,
                    "score": v / 1000000
                    + (1.0 if analysis.get("opportunity") == "HIGH" else 0),
                }
            )

        # Sort by AI score
        scored.sort(key=lambda x: x["score"], reverse=True)
        top_5 = scored[:5]

        # Fetch recent trades for top markets for entry-zone analysis
        markets_for_entry = []
        for item in top_5:
            m = dict(item["market"])
            mid = m.get("id")
            if mid:
                try:
                    trades = polymarket_api.get_market_trades(mid, limit=20) or []
                    m["recent_trades"] = trades
                except Exception:
                    m["recent_trades"] = []
            else:
                m["recent_trades"] = []
            markets_for_entry.append(m)

        # Entry zone analysis
        entry_zones = []
        if markets_for_entry:
            try:
                entry_zones = ai_filter.analyze_entry_zones(markets_for_entry)
            except Exception:
                entry_zones = [
                    {"entry_zone": "WAIT", "reason": "", "confidence": "low"}
                ] * len(markets_for_entry)

        if top_5:
            report = "📊 AI MARKET REPORT - Optimal Entry Points\n\n"
            for i, item in enumerate(top_5, 1):
                m = item["market"]
                q = m.get("question", "")[:60]
                v = item["volume"]
                odds = item["odds"]
                ana = item["analysis"]
                ez = entry_zones[i - 1] if i <= len(entry_zones) else {}

                # Get odds directly from market for override logic
                import json as json_mod
                raw_prices = m.get("outcomePrices")
                prices = None
                if raw_prices:
                    try:
                        prices = json_mod.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                    except:
                        pass
                yes_pct = float(prices[0]) if prices and len(prices) >= 1 else (odds.get('yes') if odds else None)

                # Profitability gate for report outputs:
                # avoid near-certain legs with no practical upside.
                min_gross_return_pct = float(
                    config.get("ai_report_min_gross_return_pct", 8.0) or 8.0
                )
                zone = (ez.get("entry_zone", "") or "").upper()
                if yes_pct is not None and zone in ("BUY_YES", "BUY_NO"):
                    side_price = yes_pct if zone == "BUY_YES" else (1 - yes_pct)
                    if side_price > 0:
                        gross_return_pct = ((1.0 / side_price) - 1.0) * 100.0
                        if side_price >= 0.97 or gross_return_pct < min_gross_return_pct:
                            ez = {
                                "entry_zone": "WAIT",
                                "confidence": "low",
                                "reason": f"Skipped: only {gross_return_pct:.1f}% gross upside before fees/slippage.",
                            }

                report += f"{i}. {q}\n"
                report += f"   Vol: ${v:,.0f} | "
                if odds:
                    report += f"YES: {odds.get('yes', 0) * 100:.0f}% | NO: {odds.get('no', 0) * 100:.0f}%"
                report += "\n"

                # Entry zone from AI
                zone = ez.get("entry_zone", "")
                reason = (
                    ez.get("reason", "")
                    or ana.get("analysis", "")
                    or ana.get("trigger", "")
                )
                conf = ez.get("confidence", "")
                if zone:
                    report += f"   ENTRY: {zone}"
                    if conf:
                        report += f" ({conf})"
                    report += "\n"
                if reason:
                    report += f"   -> {reason[:80]}\n"
                report += "\n"

            # Send report
            combined.send_to_alerts(report)
            print("[*] AI Report sent to alerts")
        else:
            # No high-volume markets - still confirm job ran
            combined.send_to_alerts(
                "📊 AI MARKET REPORT - No high-volume markets (>$50k) found this cycle."
            )
            print("[*] AI Report sent (no high-volume markets)")
    except Exception as e:
        print(f"   AI Report error: {e}")


def monitor(
    _args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Run continuous monitoring mode with convergence detection."""
    print("Starting PolySuite monitor...")
    if not ai_filter.is_available():
        print(
            "[!] AI providers unavailable: running deterministic alert logic. Set GROQ_API_KEY or OPENROUTER_API_KEY to enable AI refinement."
        )
    print(f"Polling interval: {config.polling_interval}s")
    print(f"Win rate threshold: {config.win_rate_threshold}%")
    print(
        f"Leaderboard import: every {config.leaderboard_import_interval // 86400} days"
    )

    # Check what's configured
    has_discord = bool(config.discord_webhook_url)
    has_telegram = bool(config.telegram_bot_token and config.telegram_chat_id)

    if has_discord:
        print("Discord: [OK] configured")
    else:
        print("Discord: [X] not configured")

    if has_telegram:
        print("Telegram: [OK] configured")
    else:
        print(
            "Telegram: [X] not configured (set telegram_bot_token and telegram_chat_id)"
        )

    print("Press Ctrl+C to stop\n")

    polymarket_api = api_factory.get_polymarket_api()
    dispatcher = AlertDispatcher(
        config.discord_webhook_url, cooldown_seconds=config.alert_cooldown
    )

    backtest_storage = BacktestStorage()
    combined = CombinedDispatcher(config, backtest_storage)

    telegram = TelegramDispatcher(config.telegram_bot_token, config.telegram_chat_id)
    detector = ConvergenceDetector(
        storage,
        threshold=config.win_rate_threshold,
        api_factory=api_factory,
        time_window_hours=config.convergence_time_window_hours,
        max_market_age_hours=config.convergence_max_market_age_hours,
        early_entry_minutes=config.convergence_early_entry_minutes,
    )
    discovery = MarketDiscovery(api_factory, config.tracked_categories)
    leaderboard_importer = LeaderboardImporter(api_factory)
    smart_money_detector = SmartMoneyDetector(api_factory)

    event_alerter = EventAlerter(
        api_factory,
        new_market_hours=config.new_market_alert_hours,
        volume_spike_multiplier=config.volume_spike_multiplier,
    )

    qualifier = Qualifier(
        min_volume=config.min_volume_for_alert,
        min_expiring_hours=1.0,
        strict_mode=config.qualification_strict_mode,
    )

    calculator = WalletCalculator(api_factory)

    # Track markets we've alerted on - with timestamps for expiration
    alerted_markets: dict = {}  # market_id -> last_alert_time
    alerted_insider_wallets: set = set()
    alerted_crypto_markets: dict = {}
    alerted_sports_markets: dict = {}
    alerted_politics_markets: dict = {}
    alerted_kalshi_markets: dict = {}
    alerted_jupiter_markets: dict = {}
    ALERT_EXPIRY_MINUTES = 720  # 12 hours = twice per day

    # Insider signal (high priority for copy traders)
    last_insider_signal_check = 0
    insider_signal_interval = config.get("insider_signal_interval", 300)  # 5 min

    # Contrarian long-shot (high vol one side, high payout other)
    last_contrarian_check = 0
    contrarian_interval = config.get("contrarian_interval", 600)

    # Track last imports
    last_smart_money_import = 0  # Import immediately on first run
    import_interval = config.leaderboard_import_interval

    # Health check / heartbeat
    last_health_check = 0
    last_ai_summary = 0  # AI daily summary
    last_ai_report = 0  # AI 30-min report with optimal entry
    last_trend_scan = 0  # Trend scanner
    trend_scan_interval = 900  # 15 minutes
    ai_report_interval = 1800  # 30 minutes - AI optimal entry report
    whale_min_size = config.whale_min_size
    whale_check_interval = config.whale_check_interval
    whale_alert_cooldown = config.whale_alert_cooldown
    last_whale_alert_time = 0
    health_check_interval = 9000  # Every 2.5 hours (only if no alerts)

    # Database backup
    last_backup = 0
    backup_interval = 21600  # Every 6 hours

    # Background vetting - vet leaderboard wallets, build curated list (no auto-add)
    last_background_vetting = 0
    background_vetting_interval = config.background_vetting_interval

    # Weekly wallet list - 10-30 vetted wallets to Discord/Telegram
    last_wallet_list_sent = 0
    wallet_list_interval = config.wallet_list_interval
    wallet_list_min = config.wallet_list_min
    wallet_list_max = config.wallet_list_max
    suggestion_tracking_enabled = bool(config.get("suggestion_tracking_enabled", True))
    suggestion_eval_interval = int(config.get("suggestion_eval_interval", 900) or 900)
    suggestion_report_interval = int(
        config.get("suggestion_report_interval", wallet_list_interval)
        or wallet_list_interval
    )
    suggestion_report_days = int(config.get("suggestion_report_days", 7) or 7)
    suggestion_stake_usd = float(config.get("suggestion_stake_usd", 100.0) or 100.0)
    last_suggestion_eval = 0
    last_suggestion_report = 0

    # Alert check intervals - more aggressive
    new_market_check_interval = 60  # Check for new markets every 1 min
    volume_check_interval = 30  # Check volume every 30 seconds

    crypto_short_term_interval = config.crypto_short_term_interval
    sports_alert_interval = config.sports_alert_interval
    politics_alert_interval = config.politics_alert_interval

    last_crypto_short_term_check = 0
    last_sports_alert_check = 0
    last_politics_alert_check = 0
    kalshi_jupiter_interval = config.kalshi_jupiter_interval
    last_kalshi_jupiter_check = 0

    # Start Telegram bot in background for interactive commands
    telegram_bot = None
    if has_telegram:
        import threading

        telegram_bot = TelegramBot(
            config.telegram_bot_token, storage, config, api_factory
        )
        telegram_thread = threading.Thread(
            target=telegram_bot.run, daemon=True, name="TelegramBot"
        )
        telegram_thread.start()
        print("[*] Telegram bot started - /ask, /connectbankr commands available")

    # Start Discord bot in background for slash commands
    discord_bot = None
    if config.discord_bot_token:
        import threading

        discord_bot = DiscordBot(config.discord_bot_token, storage, config, api_factory)
        discord_thread = threading.Thread(
            target=discord_bot.run_bot, daemon=True, name="DiscordBot"
        )
        discord_thread.start()
        print("[*] Discord bot started - /bankr, /markets commands available")

    # Copy trading (Phase D): RTDS -> qualify -> execute
    copy_engine = None
    if config.get("copy_enabled"):
        try:
            from src.copy.engine import CopyEngine
            from src.copy.storage import get_copy_target_addresses
            from src.auth.credential_store import CredentialStore

            if get_copy_target_addresses():
                cred_store = CredentialStore()
                cfg = config.config if hasattr(config, "config") else config
                copy_engine = CopyEngine(cfg, credential_store=cred_store)
                copy_engine.start()
                print("[*] Copy engine started (RTDS + CLOB)")
            else:
                print("[*] Copy enabled but no targets - add via /copy add")
        except RuntimeError as e:
            if "CREDENTIAL_ENCRYPTION_KEY" in str(e):
                print(
                    "[*] Copy enabled but CREDENTIAL_ENCRYPTION_KEY not set - copy in dry-run only"
                )
            else:
                print(f"[!] Copy engine error: {e}")
        except Exception as e:
            print(f"[!] Copy engine failed to start: {e}")

    # --- Monitor loop: INGEST (API) → PROCESS (qualifier/AI/vetting) → DISPATCH (CombinedDispatcher queue → worker) ---
    # See RESEARCH.md §9 for architecture and target pipeline (API → Worker → DB → Worker → Cache → Worker).
    while True:
        try:
            import traceback

            current_time = time.time()

            # Send test alert on first run
            if last_health_check == 0:
                test_msg = "✅ PolySuite started! Bot is running."
                combined.send_health(test_msg)
                print(f"[*] Sent startup alert to Discord & Telegram")

            # Send health check only if no alerts sent recently (every 2.5 hrs max)
            if current_time - last_health_check > health_check_interval:
                # Only send if no alerts in the last 2 hours
                if current_time - combined.get_last_alert_time() > 7200:
                    health_msg = f"HEARTBEAT - PolySuite running. Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    combined.send_health(health_msg)
                    last_health_check = current_time

                # AI Daily Summary (once per day) - deprioritized, gated by config
                if (
                    config.ai_daily_summary_enabled
                    and current_time - last_ai_summary > 86400
                ):  # 24 hours
                    try:
                        print("\n[*] Generating AI daily summary...")
                        # INGEST: API → aggregator.get_polymarkets
                        markets = aggregator.get_polymarkets(limit=20)
                        if markets:
                            summary = ai_filter.summarize_markets(markets)
                            text = summary.get("summary", "")
                            if text and "No summary" not in text:
                                combined.send_health(
                                    f"📊 AI DAILY SUMMARY\n{text[:500]}"
                                )
                                last_ai_summary = current_time
                            else:
                                print(f"[AI Summary] No summary generated")
                    except Exception as e:
                        print(f"[AI Summary] Error: {e}")

            # Trend scanner (pump.fun) - deprioritized, gated by config
            if (
                config.trend_scanner_enabled
                and current_time - last_trend_scan > trend_scan_interval
            ):
                try:
                    print("\n[*] Scanning for trends...")
                    alerts = trendscanner.scan_all()
                    for alert in alerts:
                        token = alert.get("token", {})
                        # Filter for quality
                        try:
                            mc = float(token.get("usd_market_cap", 0) or 0)
                            if mc < 50000:
                                continue  # Skip low cap
                        except:
                            continue

                        symbol = token.get("symbol", "?")

                        msg = formatter.format_trend(token, "")

                        combined.send_to_trends(msg)  # Send to trends channel
                        print(f"   Found: {symbol} (${mc / 1000:.1f}k)")
                    last_trend_scan = current_time
                except Exception as e:
                    print(f"[TrendScanner] Error: {e}")

            # Database backup
            if current_time - last_backup > backup_interval:
                print("\n[*] Creating database backup...")
                backup_path = storage.backup()
                if backup_path:
                    backup_count = storage.get_backup_count()
                    db_size = storage.get_db_size()
                    combined.send_health(
                        f"DB BACKUP - Saved: {backup_path[-30:]}. Total backups: {backup_count}, Size: {db_size / 1024 / 1024:.1f}MB"
                    )
                # Cleanup old backups
                storage.cleanup_old_backups(keep_days=7)
                last_backup = current_time

            # Background vetting - vet leaderboard, build curated list (no auto-add)
            if current_time - last_background_vetting > background_vetting_interval:
                try:
                    print("\n[*] Background vetting: vetting leaderboard wallets...")
                    importer = LeaderboardImporter(api_factory)
                    vetter = WalletVetting(api_factory)
                    min_bet = getattr(config, "min_bet_size", 10.0) or 10.0
                    traders = importer.fetch_leaderboard(limit=20)
                    curated = []
                    shared_market_cache = {}
                    vetted_count = 0
                    for t in traders:
                        addr = t.get("address")
                        if not addr:
                            continue
                        # Use source as platform (polymarket/jupiter/kalshi)
                        platform = t.get("source", "polymarket")
                        result = vetter.vet_wallet(
                            addr,
                            min_bet=min_bet,
                            market_cache=shared_market_cache,
                            platform=platform,
                        )

                        # ALWAYS save vetting results to database (even if failed)
                        if result:
                            storage.update_wallet_vetting(
                                addr,
                                bot_score=result.get("bot_score"),
                                unresolved_exposure_usd=None,
                                total_pnl=result.get("total_pnl"),
                                roi_pct=result.get("roi_pct"),
                                conviction_score=result.get("conviction_score"),
                                is_specialty=result.get("is_specialty", False),
                                specialty_note=result.get("specialty_note"),
                                specialty_market_id=result.get("specialty_market_id"),
                                specialty_category=result.get("specialty_category"),
                            )
                            vetted_count += 1

                        if result and result.get("passed"):
                            entry = {
                                "address": addr,
                                "nickname": t.get("userName")
                                or t.get("username")
                                or addr[:12] + "...",
                                "bot_score": result.get("bot_score"),
                                "win_rate_real": result.get("win_rate_real"),
                                "avg_bet_size": result.get("avg_bet_size"),
                                "total_pnl": result.get("total_pnl"),
                                "roi_pct": result.get("roi_pct"),
                                "conviction_score": result.get("conviction_score"),
                                "reliability_score": result.get("reliability_score"),
                                "current_win_streak": result.get("current_win_streak"),
                                "recent_win_rate": result.get("recent_win_rate"),
                                "estimated_fees_paid": result.get(
                                    "estimated_fees_paid"
                                ),
                                "top_category": result.get("top_category"),
                            }
                            if result.get("specialty_or_hot_streak_note"):
                                entry["specialty_or_hot_streak_note"] = result.get(
                                    "specialty_or_hot_streak_note"
                                )
                            curated.append(entry)
                    print(f"   [*] Vetted {vetted_count} wallets, {len(curated)} passed")
                    if curated:
                        vetting_path = Path("data/vetted_leaderboard.json")
                        vetting_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(vetting_path, "w") as f:
                            json.dump(
                                {
                                    "updated": datetime.utcnow().isoformat(),
                                    "wallets": curated,
                                },
                                f,
                                indent=2,
                            )
                        print(
                            f"[*] Background vetting: {len(curated)} passed, saved to {vetting_path}"
                        )
                    last_background_vetting = current_time
                except Exception as e:
                    print(f"[Background vetting] Error: {e}")
                    last_background_vetting = current_time  # Avoid rapid retries

            # Weekly wallet list - re-vet at broadcast time, send 10-30 to Discord & Telegram
            if current_time - last_wallet_list_sent >= wallet_list_interval:
                try:
                    print("\n[*] Weekly wallet list: vetting leaderboard...")
                    importer = LeaderboardImporter(api_factory)
                    vetter = WalletVetting(api_factory)
                    min_bet = getattr(config, "min_bet_size", 10.0) or 10.0
                    traders = importer.fetch_leaderboard(limit=50)
                    passed = []
                    shared_market_cache = {}
                    vetted_count = 0
                    for t in traders:
                        addr = t.get("address")
                        if not addr:
                            continue
                        result = vetter.vet_wallet(
                            addr, min_bet=min_bet, market_cache=shared_market_cache
                        )

                        # ALWAYS save vetting results to database (even if failed)
                        if result:
                            storage.update_wallet_vetting(
                                addr,
                                bot_score=result.get("bot_score"),
                                unresolved_exposure_usd=None,
                                total_pnl=result.get("total_pnl"),
                                roi_pct=result.get("roi_pct"),
                                conviction_score=result.get("conviction_score"),
                                is_specialty=result.get("is_specialty", False),
                                specialty_note=result.get("specialty_note"),
                                specialty_market_id=result.get("specialty_market_id"),
                                specialty_category=result.get("specialty_category"),
                            )
                            vetted_count += 1

                        if result and result.get("passed"):
                            passed.append(
                                {
                                    "address": addr,
                                    "nickname": t.get("userName")
                                    or t.get("username")
                                    or addr[:12] + "...",
                                    "bot_score": result.get("bot_score"),
                                    "win_rate_real": result.get("win_rate_real"),
                                    "avg_bet_size": result.get("avg_bet_size"),
                                    "reliability_score": result.get(
                                        "reliability_score"
                                    ),
                                    "current_win_streak": result.get(
                                        "current_win_streak"
                                    ),
                                    "recent_win_rate": result.get("recent_win_rate"),
                                    "top_category": result.get("top_category"),
                                }
                            )
                    print(f"   [*] Vetted {vetted_count} wallets, {len(passed)} passed")
                    passed.sort(
                        key=lambda x: (
                            x.get("reliability_score") or 0,
                            x.get("current_win_streak") or 0,
                            x.get("recent_win_rate") or 0,
                            x.get("win_rate_real") or 0,
                            x.get("avg_bet_size") or 0,
                        ),
                        reverse=True,
                    )
                    to_send = passed[:wallet_list_max]
                    if len(to_send) >= wallet_list_min:
                        msg = formatter.format_wallet_list(to_send)
                        if msg:
                            combined.send_to_alerts(msg)
                            print(
                                f"[*] Weekly wallet list: sent {len(to_send)} wallets to Discord & Telegram"
                            )
                            last_wallet_list_sent = current_time
                    else:
                        print(
                            f"[*] Weekly wallet list: only {len(to_send)} passed (min {wallet_list_min}), skipping"
                        )
                        last_wallet_list_sent = (
                            current_time  # Avoid retrying every loop
                        )
                except Exception as e:
                    print(f"[Weekly wallet list] Error: {e}")
                    last_wallet_list_sent = current_time  # Avoid rapid retries

            # AI report every 30 minutes - only when AI providers are configured
            if ai_filter.is_available() and current_time - last_ai_report > ai_report_interval:
                _generate_ai_market_report(polymarket_api, combined, config)
                last_ai_report = current_time

            # Curated wallet activity - gated to vetted/curated wallets when enabled
            if (
                config.whale_alerts_enabled
                and current_time - last_smart_money_import > whale_check_interval
            ):
                print("\n[*] Checking curated wallets for recent activity...")

                # Whale pivot: prefer vetted_leaderboard.json; fallback to tracked wallets
                wallets = []
                vetting_path = Path("data/vetted_leaderboard.json")
                if vetting_path.exists():
                    try:
                        with open(vetting_path) as f:
                            data = json.load(f)
                        vetted = data.get("wallets", [])
                        if vetted:
                            from src.wallet import Wallet

                            wallets = [
                                Wallet(
                                    address=v["address"],
                                    nickname=v.get(
                                        "nickname", v["address"][:12] + "..."
                                    ),
                                )
                                for v in vetted
                                if v.get("address")
                            ]
                            print(
                                f"   Using {len(wallets)} vetted wallets from {vetting_path}"
                            )
                    except Exception as e:
                        print(f"   Vetted load error: {e}")
                if not wallets:
                    wallets = storage.list_wallets()
                pm = polymarket_api

                # INGEST: DB (vetted_leaderboard.json) + API (polymarket_api.get_wallet_trades)
                # Only trades from last 6 hours
                import time as _time

                whale_hours_window = 6
                after_ts = int(_time.time()) - (whale_hours_window * 3600)

                whale_trades = []
                market_cache = {}  # market_id -> {question, slug}

                for wallet in wallets:
                    try:
                        trades = (
                            pm.get_wallet_trades(
                                wallet.address, limit=100, after=after_ts
                            )
                            or []
                        )

                        for t in trades:
                            mid = str(t.get("conditionId") or t.get("market") or "")
                            if not mid:
                                continue
                            size = float(t.get("size", 0) or 0)
                            price = float(t.get("price", 0) or 0)
                            # USD value: size*price (size in shares) or use value/amount if present
                            trade_usd = float(
                                t.get("value") or t.get("amount") or 0
                            ) or (size * price if price else size)
                            if trade_usd < whale_min_size:
                                continue

                            # Fetch market for question/slug (cache for reuse)
                            if mid not in market_cache:
                                m = pm.get_market(mid) or pm.get_market_details(mid)
                                market_cache[mid] = {
                                    "question": (
                                        m.get("question") or m.get("title") or "Unknown"
                                    )[:35]
                                    if m
                                    else "Unknown",
                                    "slug": m.get("slug", "") if m else "",
                                }

                            q = market_cache[mid]["question"]
                            whale_trades.append(
                                {
                                    "wallet": wallet.nickname,
                                    "address": wallet.address[:10] + "...",
                                    "side": t.get("outcome") or t.get("side", "?"),
                                    "size": trade_usd,
                                    "question": q,
                                    "market_id": mid,
                                    "entry_price": price,
                                    "slug": market_cache[mid].get("slug", ""),
                                }
                            )

                    except Exception as e:
                        print(f"Whale check error {wallet.address[:12]}...: {e}")

                # Send batched whale alerts (to alerts channel) - respect cooldown
                if (
                    whale_trades
                    and (current_time - last_whale_alert_time) >= whale_alert_cooldown
                ):
                    print(
                        f"    -> Sending {len(whale_trades)} curated wallet trades in batch"
                    )

                    # AI summary with triggers (skip for small batches to reduce API calls)
                    ai_summary = ""
                    if len(whale_trades) >= 2:
                        try:
                            ai_summary = ai_filter.analyze_whale_trades(
                                whale_trades[:10]
                            )
                            if ai_summary and "TRIGGER:" in ai_summary:
                                trig = (
                                    ai_summary.split("TRIGGER:")[1]
                                    .split("\n")[0]
                                    .strip()
                                )
                                print(f"   🐋 Trigger: {trig}")
                        except Exception:
                            pass

                    # Entry zone from top trade's market
                    entry_zone, conviction, entry_reason = "", "", ""
                    if whale_trades:
                        try:
                            top = max(whale_trades, key=lambda t: t.get("size", 0))
                            q = top.get("question", "Unknown")
                            ep = top.get("entry_price")
                            price = float(ep) if ep is not None else 0.5
                            vol = sum(
                                t.get("size", 0)
                                for t in whale_trades
                                if t.get("question") == q
                            )
                            market_dict = {
                                "question": q,
                                "volume": vol,
                                "outcomePrices": [price, 1 - price],
                            }
                            zones = ai_filter.analyze_entry_zones([market_dict])
                            if zones:
                                z = zones[0]
                                entry_zone = z.get("entry_zone", "")
                                conviction = z.get("confidence", "")
                                entry_reason = (z.get("reason", "") or "")[:100]
                        except Exception:
                            pass

                    # PROCESS: formatter; DISPATCH: combined.send_to_alerts → queue → worker
                    msg = formatter.format_whale_batch(
                        whale_trades,
                        ai_summary,
                        entry_zone=entry_zone,
                        conviction=conviction,
                        entry_reason=entry_reason,
                    )
                    combined.send_to_alerts(msg)
                    last_whale_alert_time = current_time
                elif (
                    whale_trades
                    and (current_time - last_whale_alert_time) < whale_alert_cooldown
                ):
                    print(
                        f"    -> Skipping curated wallet alert (cooldown: {whale_alert_cooldown}s)"
                    )

                last_smart_money_import = current_time

            # Kalshi & Jupiter - INGEST (API) → PROCESS (qualifier/AI) → DISPATCH (combined)
            if current_time - last_kalshi_jupiter_check >= kalshi_jupiter_interval:
                last_kalshi_jupiter_check = current_time
                try:
                    print("[*] Fetching Kalshi & Jupiter markets...")
                    kalshi_markets = aggregator.get_kalshi_markets(limit=50)
                    jupiter_markets = aggregator.get_jupiter_markets()
                    print(f"[Kalshi] Fetched {len(kalshi_markets)} markets")
                    print(f"[Jupiter] Fetched {len(jupiter_markets)} markets")
                    # Kalshi: top 3 by volume, only send if volume >= $100 (trade signal)
                    _dispatch_market_alerts(
                        kalshi_markets,
                        100,
                        3,
                        ai_filter,
                        formatter.format_kalshi_market,
                        combined,
                        "kalshi",
                        "Kalshi",
                        backtest_storage=backtest_storage,
                    )
                    # Jupiter: top 3, only send if volume >= $100 (trade signal)
                    if config.jupiter_alerts_enabled:
                        _dispatch_market_alerts(
                            jupiter_markets,
                            100,
                            3,
                            ai_filter,
                            formatter.format_jupiter_market,
                            combined,
                            "jupiter",
                            "Jupiter",
                            use_market_category=True,
                            backtest_storage=backtest_storage,
                        )
                except Exception as e:
                    print(f"[Kalshi/Jupiter] Error: {e}")

            # Get high performers
            all_wallets = storage.list_wallets()
            trade_volume_threshold = config.trade_volume_threshold

            # Filter wallets by trade volume
            high_performers = [
                w
                for w in all_wallets
                if w.trade_volume >= trade_volume_threshold
                and w.is_high_performer(config.win_rate_threshold)
            ]

            if not high_performers:
                print("No high performers to track. Add wallets first!")
                time.sleep(config.polling_interval)
                continue

            # ===== PRIORITY 1: INSIDER SIGNAL (high priority for copy traders) =====
            if (
                config.get("insider_signal_enabled", True)
                and current_time - last_insider_signal_check >= insider_signal_interval
            ):
                last_insider_signal_check = current_time
                try:
                    print("\n[*] Checking for insider signals...")
                    from src.alerts.insider_signal import InsiderSignalDetector
                    from src.alerts.insider import InsiderDetector

                    hashdive = None
                    if config.get("hashdive_api_key"):
                        hashdive = (
                            api_factory.get_hashdive_client()
                            if hasattr(api_factory, "get_hashdive_client")
                            else None
                        )
                    insider_detector = InsiderSignalDetector(
                        hashdive_client=hashdive,
                        polymarket_api=polymarket_api,
                        insider_detector=InsiderDetector(),
                        api_factory=api_factory,
                        min_trade_usd=getattr(
                            config, "insider_signal_min_trade_usd", 5000
                        ),
                        fresh_max_trades=getattr(
                            config, "insider_signal_fresh_max_trades", 10
                        ),
                        liquidity_threshold=config.get(
                            "weird_wallet_liquidity_threshold", 0.02
                        ),
                        niche_volume_max=config.get(
                            "weird_wallet_niche_volume_max", 50000
                        ),
                    )
                    # INGEST: PolymarketWhaleClient/HashDive + polymarket_api; PROCESS: InsiderSignalDetector; DISPATCH: combined
                    signals = insider_detector.scan_for_signals(limit=5)
                    for sig in signals:
                        addr = sig.get("address", "")
                        if addr and addr not in alerted_insider_wallets:
                            msg = formatter.format_insider_signal(sig)
                            combined.send_to_alerts(msg, category="insider")
                            alerted_insider_wallets.add(addr)
                            print(f"   🔴 INSIDER: {addr[:16]}...")
                except Exception as e:
                    print(f"[InsiderSignal] Error: {e}")

            # ===== CONTRARIAN LONG-SHOT (when enabled) =====
            if (
                config.get("contrarian_alerts_enabled", False)
                and current_time - last_contrarian_check >= contrarian_interval
            ):
                last_contrarian_check = current_time
                try:
                    from src.alerts.contrarian import ContrarianDetector

                    detector = ContrarianDetector(
                        polymarket_api=polymarket_api,
                        min_volume=getattr(config, "contrarian_min_volume", 10000)
                        or 10000,
                        min_imbalance=getattr(config, "contrarian_min_imbalance", 0.6)
                        or 0.6,
                        payout_range=(
                            getattr(config, "contrarian_payout_min", 0.20) or 0.20,
                            getattr(config, "contrarian_payout_max", 0.40) or 0.40,
                        ),
                        limit=3,
                    )
                    # INGEST: polymarket_api; PROCESS: ContrarianDetector; DISPATCH: combined
                    signals = detector.scan()
                    for sig in signals:
                        msg = formatter.format_contrarian(sig)
                        combined.send_to_alerts(msg, category="contrarian")
                        print(f"   📊 Contrarian: {sig.get('question', '')[:40]}...")
                except Exception as e:
                    print(f"[Contrarian] Error: {e}")

            # ===== PRIORITY 2: CRYPTO 5MIN/15MIN MARKETS =====
            # Batch fetch: 1 API call for crypto/sports/politics instead of 3
            print("[*] Checking crypto markets...")
            category_markets = event_alerter.fetch_markets_for_categories(limit=500)
            crypto_markets = category_markets.get("crypto", [])
            sports_markets = category_markets.get("sports", [])
            politics_markets = category_markets.get("politics", [])
            all_market_ids = category_markets.get("all_market_ids", set())
            crypto_short_term_markets = event_alerter.check_crypto_short_term_markets(
                limit=50
            )

            # Crypto 5M/15M dedicated check - run every 1-2 min, send to alerts
            if (
                current_time - last_crypto_short_term_check
                >= crypto_short_term_interval
            ):
                last_crypto_short_term_check = current_time
                if crypto_short_term_markets:
                    top_short_term = sorted(
                        crypto_short_term_markets,
                        key=lambda x: float(x.get("volume", 0) or 0),
                        reverse=True,
                    )[:5]
                    entry_zones_st = []
                    try:
                        entry_zones_st = ai_filter.analyze_entry_zones(top_short_term)
                    except Exception:
                        entry_zones_st = [
                            {"entry_zone": "WAIT", "reason": "", "confidence": "low"}
                        ] * len(top_short_term)
                    for idx, m in enumerate(top_short_term):
                        market_id = m.get("id") or m.get("conditionId") or ""
                        # Skip if alerted in last 24 hours
                        if (
                            alerted_crypto_markets.get(market_id)
                            and (
                                current_time - alerted_crypto_markets.get(market_id, 0)
                            )
                            < ALERT_EXPIRY_MINUTES * 60
                        ):
                            continue
                        ez = (
                            entry_zones_st[idx]
                            if idx < len(entry_zones_st)
                            else {
                                "entry_zone": "WAIT",
                                "reason": "",
                                "confidence": "low",
                            }
                        )
                        msg = formatter.format_crypto_short_term(
                            m,
                            entry_zone=ez.get("entry_zone", "WAIT"),
                            conviction=ez.get("confidence", "low"),
                            entry_reason=ez.get("reason", ""),
                        )
                        combined.send_to_alerts(msg, category="crypto_short_term")
                        _record_actionable_suggestion(
                            backtest_storage,
                            m,
                            ez.get("entry_zone", "WAIT"),
                            "crypto_short_term",
                            "crypto_short_term",
                            conviction=ez.get("confidence", "low"),
                            entry_reason=ez.get("reason", ""),
                        )
                        alerted_crypto_markets[market_id] = current_time

            # Sports dedicated check - send top 1 to reduce noise
            if current_time - last_sports_alert_check >= sports_alert_interval:
                last_sports_alert_check = current_time
                if sports_markets:
                    top_sports = sorted(
                        sports_markets,
                        key=lambda x: float(x.get("volume", 0) or 0),
                        reverse=True,
                    )[:1]
                    for m in top_sports:
                        market_id = m.get("id") or m.get("conditionId") or ""
                        # Skip if alerted in last 12 hours
                        if (
                            alerted_sports_markets.get(market_id)
                            and (
                                current_time - alerted_sports_markets.get(market_id, 0)
                            )
                            < ALERT_EXPIRY_MINUTES * 60
                        ):
                            continue
                        vol = float(m.get("volume", 0) or 0)
                        if vol >= 5000:  # Only liquid sports
                            ez = {
                                "entry_zone": "WAIT",
                                "reason": "",
                                "confidence": "low",
                            }
                            try:
                                zones = ai_filter.analyze_entry_zones([m])
                                ez = zones[0] if zones else ez
                            except Exception:
                                pass
                            msg = formatter.format_sports_market(
                                m,
                                entry_zone=ez.get("entry_zone", "WAIT"),
                                conviction=ez.get("confidence", "low"),
                                entry_reason=ez.get("reason", ""),
                            )
                            combined.send_to_alerts(msg, category="sports")
                            _record_actionable_suggestion(
                                backtest_storage,
                                m,
                                ez.get("entry_zone", "WAIT"),
                                "sports",
                                "sports",
                                conviction=ez.get("confidence", "low"),
                                entry_reason=ez.get("reason", ""),
                            )
                            alerted_sports_markets[market_id] = current_time

            # Politics dedicated check - send top 1 to reduce noise
            if current_time - last_politics_alert_check >= politics_alert_interval:
                last_politics_alert_check = current_time
                if politics_markets:
                    top_politics = sorted(
                        politics_markets,
                        key=lambda x: float(x.get("volume", 0) or 0),
                        reverse=True,
                    )[:1]

                    from datetime import datetime, timedelta
                    import re

                    def is_expired_event(question: str) -> bool:
                        """Check if question refers to a date that has passed."""
                        q = question.lower()
                        # Match patterns like "on March 3", "by March 3", "before March 3"
                        patterns = [
                            r"(?:on|by|before|until|on or before)\s+(\w+)\s+(\d{1,2})",
                            r"(\w+)\s+(\d{1,2}),?\s*(\d{4})?",
                        ]
                        months = {
                            "january": 1,
                            "february": 2,
                            "march": 3,
                            "april": 4,
                            "may": 5,
                            "june": 6,
                            "july": 7,
                            "august": 8,
                            "september": 9,
                            "october": 10,
                            "november": 11,
                            "december": 12,
                        }
                        now = datetime.now()
                        for pattern in patterns:
                            match = re.search(pattern, q)
                            if match:
                                try:
                                    month_name = match.group(1).lower()
                                    day = int(match.group(2))
                                    year = (
                                        int(match.group(3))
                                        if match.group(3)
                                        else now.year
                                    )
                                    if month_name in months:
                                        month = months[month_name]
                                        event_date = datetime(year, month, day)
                                        # If date has passed (and it's not far in the future), mark expired
                                        if event_date < now:
                                            return True
                                except:
                                    pass
                        return False

                    # Filter out meme/joke markets (celebrity presidential elections, etc.)
                    non_political_figures = [
                        "lebron",
                        "taylor swift",
                        "beyonce",
                        "elon",
                        "musk",
                        "drake",
                        "kanye",
                        "kim kardashian",
                        "cristiano",
                        "messi",
                        "tom brady",
                    ]
                    for m in top_politics:
                        market_id = m.get("id") or m.get("conditionId") or ""
                        # Skip if alerted in last 12 hours
                        if (
                            alerted_politics_markets.get(market_id)
                            and (
                                current_time
                                - alerted_politics_markets.get(market_id, 0)
                            )
                            < ALERT_EXPIRY_MINUTES * 60
                        ):
                            continue
                        vol = float(m.get("volume", 0) or 0)
                        question = m.get("question") or ""
                        question_lower = question.lower()

                        # Skip expired events (date already passed)
                        if is_expired_event(question):
                            continue

                        # Skip meme markets
                        if (
                            "president" in question_lower
                            or "election" in question_lower
                        ):
                            if any(
                                figure in question_lower
                                for figure in non_political_figures
                            ):
                                continue
                            # Skip if odds are too extreme (likely joke market)
                            yes_pct = m.get("yes_pct")
                            if yes_pct and (yes_pct < 0.05 or yes_pct > 0.95):
                                continue
                        if vol >= 10000:  # Higher bar for politics
                            ez = {
                                "entry_zone": "WAIT",
                                "reason": "",
                                "confidence": "low",
                            }
                            try:
                                zones = ai_filter.analyze_entry_zones([m])
                                ez = zones[0] if zones else ez
                            except Exception:
                                pass
                            msg = formatter.format_politics_market(
                                m,
                                entry_zone=ez.get("entry_zone", "WAIT"),
                                conviction=ez.get("confidence", "low"),
                                entry_reason=ez.get("reason", ""),
                            )
                            combined.send_to_alerts(msg, category="politics")
                            _record_actionable_suggestion(
                                backtest_storage,
                                m,
                                ez.get("entry_zone", "WAIT"),
                                "politics",
                                "politics",
                                conviction=ez.get("confidence", "low"),
                                entry_reason=ez.get("reason", ""),
                            )
                            alerted_politics_markets[market_id] = current_time

            # Print top actionable markets
            print(
                f"   Crypto: {len(crypto_markets)} | 5M/15M: {len(crypto_short_term_markets)} | Sports: {len(sports_markets)} | Politics: {len(politics_markets)}"
            )

            # AI picks best opportunities across all categories (include crypto 5M/15M)
            seen_ids = set()
            all_markets = []
            for m in (
                crypto_short_term_markets
                + crypto_markets
                + sports_markets
                + politics_markets
            ):
                mid = m.get("id")
                if mid and mid in seen_ids:
                    continue
                if mid:
                    seen_ids.add(mid)
                v = float(m.get("volume", 0) or 0)
                if v > 10000:  # Only liquid markets
                    all_markets.append(m)

            # AI analyze and pick best opportunities
            if all_markets:
                print("\n   === AI TOP PICKS ===")
                for m in sorted(
                    all_markets,
                    key=lambda x: float(x.get("volume", 0) or 0),
                    reverse=True,
                )[:10]:
                    try:
                        analysis = ai_filter.analyze_new_market(m)
                        q = m.get("question", "")[:45]
                        v = float(m.get("volume", 0) or 0)

                        # Get current odds
                        prices = m.get("outcomePrices", "")
                        odds_str = ""
                        if prices:
                            try:
                                if isinstance(prices, str):
                                    p = json.loads(prices)
                                else:
                                    p = prices
                                if p and len(p) >= 2:
                                    odds_str = f" YES:{float(p[0]) * 100:.0f}% NO:{float(p[1]) * 100:.0f}%"
                            except Exception:
                                pass

                        opp = analysis.get("opportunity", "LOW")
                        emoji = (
                            "⭐" if opp == "HIGH" else ("✅" if opp == "MEDIUM" else "")
                        )

                        print(f"   {emoji} ${v:>10,.0f} - {q}")
                        if odds_str:
                            print(f"      Odds: {odds_str}")
                        if analysis.get("reason"):
                            print(f"      -> {analysis.get('reason', '')[:50]}")
                    except:
                        pass

            # Show top crypto 5M/15M by volume
            if crypto_short_term_markets:
                print("\n   === TOP CRYPTO 5M/15M ===")
                for m in sorted(
                    crypto_short_term_markets,
                    key=lambda x: float(x.get("volume", 0) or 0),
                    reverse=True,
                )[:5]:
                    q = m.get("question", "")[:50]
                    v = float(m.get("volume", 0) or 0)
                    yes_pct = m.get("yes_pct")
                    yes_str = (
                        f" YES:{yes_pct * 100:.0f}%" if yes_pct is not None else ""
                    )
                    print(f"   ${v:>10,.0f}{yes_str} - {q}")

            # Show top crypto by volume
            if crypto_markets:
                print("\n   === TOP CRYPTO MARKETS ===")
                top_crypto = sorted(
                    crypto_markets,
                    key=lambda x: float(x.get("volume", 0) or 0),
                    reverse=True,
                )[:5]
                for m in top_crypto:
                    q = m.get("question", "")[:50]
                    v = float(m.get("volume", 0) or 0)
                    print(f"   ${v:>10,.0f} - {q}")
                    # AI analysis
                    try:
                        analysis = ai_filter.analyze_new_market(m)
                        if analysis.get("opportunity") == "HIGH":
                            print(f"      -> {analysis.get('reason', '')[:60]}")
                    except:
                        pass

            # Show top sports by volume
            if sports_markets:
                print("\n   === TOP SPORTS MARKETS ===")
                top_sports = sorted(
                    sports_markets,
                    key=lambda x: float(x.get("volume", 0) or 0),
                    reverse=True,
                )[:5]
                for m in top_sports:
                    q = m.get("question", "")[:50]
                    v = float(m.get("volume", 0) or 0)
                    print(f"   ${v:>10,.0f} - {q}")
                    # AI analysis
                    try:
                        analysis = ai_filter.analyze_new_market(m)
                        if analysis.get("opportunity") == "HIGH":
                            print(f"      -> {analysis.get('reason', '')[:60]}")
                    except:
                        pass

            # Show top politics by volume
            if politics_markets:
                print("\n   === TOP POLITICS MARKETS ===")
                top_politics = sorted(
                    politics_markets,
                    key=lambda x: float(x.get("volume", 0) or 0),
                    reverse=True,
                )[:5]
                for m in top_politics:
                    q = m.get("question", "")[:50]
                    v = float(m.get("volume", 0) or 0)
                    print(f"   ${v:>10,.0f} - {q}")
                    # AI analysis
                    try:
                        analysis = ai_filter.analyze_new_market(m)
                        if analysis.get("opportunity") == "HIGH":
                            print(f"      -> {analysis.get('reason', '')[:60]}")
                    except:
                        pass

            # ===== PRIORITY 3: CONVERGENCE (tracked wallets in same event) =====
            # Only alert HIGH/CRITICAL - skip NORMAL
            print("[*] Checking convergence...")
            convergences = detector.find_convergences(min_wallets=2)
            new_convergences = [
                c
                for c in convergences
                if c["market_id"] not in alerted_markets
                and (c.get("has_early_entry") or len(c.get("wallets", [])) >= 3)
            ]

            for conv in new_convergences:
                market = conv.get("market_info") or {}
                wallets = conv.get("wallets", [])

                urgency = (
                    "CRITICAL"
                    if conv.get("has_early_entry") and len(wallets) >= 3
                    else "HIGH"
                )
                emoji = "🔴" if urgency == "CRITICAL" else "🟠"

                # AI analysis for convergence
                ai_analysis = ""
                entry_zone, conviction, entry_reason = "", "", ""
                try:
                    if wallets:
                        trade_summary = [
                            {
                                "side": w.get("side", ""),
                                "entry_price": w.get("entry_price"),
                                "size": w.get("size"),
                                "question": market.get("question", "")[:30],
                            }
                            for w in wallets[:5]
                        ]
                        wallet_analysis = ai_filter.analyze_wallet(trade_summary)
                        if wallet_analysis and wallet_analysis.get("analysis"):
                            ai_analysis = wallet_analysis["analysis"][:100]
                            print(f"   🤖 Strategy: {ai_analysis[:60]}")
                        # Entry zone for RECOMMENDATION
                        zones = ai_filter.analyze_entry_zones([market])
                        if zones:
                            z = zones[0]
                            entry_zone = z.get("entry_zone", "")
                            conviction = z.get("confidence", "")
                            entry_reason = z.get("reason", "")[:100]
                except Exception:
                    pass

                # Format and send with AI reasoning and RECOMMENDATION
                msg = formatter.format_convergence(
                    market,
                    wallets,
                    conv,
                    ai_analysis,
                    entry_zone=entry_zone,
                    conviction=conviction,
                    entry_reason=entry_reason,
                )
                combined.send_to_alerts(
                    msg,
                    category="convergence",
                    backtest_meta={
                        "alert_type": "convergence",
                        "market_id": conv.get("market_id"),
                    },
                )
                _record_actionable_suggestion(
                    backtest_storage,
                    market,
                    entry_zone,
                    "convergence",
                    "convergence",
                    conviction=conviction,
                    entry_reason=entry_reason,
                )
                print(
                    f"{emoji} CONVERGENCE: {len(wallets)} traders in {market.get('question', 'Unknown')[:40]}..."
                )
                alerted_markets[conv["market_id"]] = time.time()

            if suggestion_tracking_enabled:
                if current_time - last_suggestion_eval >= suggestion_eval_interval:
                    try:
                        resolved_stats = backtest_storage.resolve_open_suggestions(
                            polymarket_api,
                            stake_usd=suggestion_stake_usd,
                            max_per_run=100,
                        )
                        if resolved_stats.get("resolved", 0):
                            print(
                                f"   [SuggestionTracker] Resolved {resolved_stats.get('resolved', 0)} (W {resolved_stats.get('wins', 0)} / L {resolved_stats.get('losses', 0)})"
                            )
                    except Exception as e:
                        print(f"[SuggestionTracker] Resolve error: {e}")
                    last_suggestion_eval = current_time

                if current_time - last_suggestion_report >= suggestion_report_interval:
                    try:
                        since_ts = datetime.utcfromtimestamp(
                            current_time - (suggestion_report_days * 86400)
                        ).isoformat()
                        summary = backtest_storage.get_suggestion_summary(since_ts)
                        if summary.get("total", 0) > 0:
                            report = _format_weekly_suggestion_report(
                                summary,
                                days=suggestion_report_days,
                                stake_usd=suggestion_stake_usd,
                            )
                            combined.send_to_alerts(report)
                            print(
                                f"[*] Weekly suggestion scorecard sent ({summary.get('total', 0)} signals)"
                            )
                    except Exception as e:
                        print(f"[SuggestionTracker] Weekly report error: {e}")
                    last_suggestion_report = current_time

            # ===== FULL MARKET SCANS (volume, odds) =====

            # Clean old markets from alerted set - reuse IDs from batch fetch
            if all_market_ids:
                # Keep only market_ids that exist in current all_market_ids
                alerted_markets = {k: v for k, v in alerted_markets.items() if k in all_market_ids}

            print(
                f"\rMonitoring {len(high_performers)} wallets | {len(convergences)} convergences",
                end="",
            )

            time.sleep(config.polling_interval)

        except KeyboardInterrupt:
            print("\n\nStopped.")
            combined.send_health("PolySuite stopped by user")
            break
        except Exception as e:
            import traceback

            print(f"\n{'=' * 60}")
            print(f"ERROR: {type(e).__name__}: {e}")
            tb = traceback.format_exc()
            print(tb)
            print(f"{'=' * 60}\n")
            # Send error alert
            error_msg = f"ERROR: {type(e).__name__}: {str(e)[:100]}"
            try:
                combined.send_health(error_msg)
            except Exception:
                pass
            time.sleep(30)  # Wait before retry to avoid rapid error loops


def check_convergence(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """One-time convergence check."""
    detector = ConvergenceDetector(
        storage,
        threshold=config.win_rate_threshold,
        api_factory=api_factory,
        time_window_hours=config.convergence_time_window_hours,
        max_market_age_hours=config.convergence_max_market_age_hours,
        early_entry_minutes=config.convergence_early_entry_minutes,
    )

    print(f"Checking for convergences (threshold: {config.win_rate_threshold}%)\n")
    print(
        f"Time window: {config.convergence_time_window_hours}h | Max market age: {config.convergence_max_market_age_hours}h | Early entry: {config.convergence_early_entry_minutes}min\n"
    )

    convergences = detector.find_convergences(min_wallets=2)

    if not convergences:
        print("No convergences found.")
        return

    print(f"Found {len(convergences)} convergence(s):\n")

    for i, conv in enumerate(convergences, 1):
        market = conv.get("market_info") or {}
        wallets = conv.get("wallets", [])

        print(f"{i}. {market.get('question', 'Unknown')[:60]}")
        print(f"   Traders ({len(wallets)}):")
        for w in wallets:
            print(
                f"   - {w['nickname']}: {w['win_rate']:.1f}% ({w['wins']}/{w['total_trades']})"
            )
        print()


def list_markets(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """List active markets."""
    api = api_factory.get_polymarket_api()
    markets = api.get_active_markets(limit=args.limit)

    if not markets:
        print("No active markets found.")
        return

    print(f"\n{'Question':<50} {'Volume':<12}")
    print("-" * 70)

    for m in markets:
        q = m.get("question", "Unknown")[:48]
        v = m.get("volume", 0)
        try:
            v = float(v)
            print(f"{q:<50} ${v:>10,.0f}")
        except (ValueError, TypeError):
            print(f"{q:<50} ${str(v):>10}")


def import_leaderboard(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Import top traders from Polymarket leaderboards. Vet-before-add (Phase 2a)."""
    importer = LeaderboardImporter(api_factory)
    vetter = WalletVetting(api_factory)
    min_bet = getattr(config, "min_bet_size", 10.0) or 10.0

    print("Fetching from Polymarket leaderboards...")
    traders = importer.fetch_leaderboard()

    if not traders:
        print("No traders found.")
        return

    print(f"\nFound {len(traders)} traders (vetting before add)...\n")

    added = 0
    skipped = 0
    rejected = 0

    for i, trader in enumerate(traders, 1):
        addr = trader.get("address")
        if not addr:
            continue
        raw_nick = (
            trader.get("userName")
            or trader.get("username")
            or trader.get("proxyWallet", f"Trader{i}")
        )
        nickname = sanitize_nickname(str(raw_nick)[:50]) or f"Trader{i}"

        # Vet before add - only add if passed
        result = vetter.vet_wallet(addr, min_bet=min_bet)
        if result and not result.get("passed"):
            rejected += 1
            continue

        wallet = Wallet(address=addr, nickname=nickname)
        if result:
            wallet.bot_score = result.get("bot_score")

        if storage.add_wallet(wallet):
            if result:
                storage.update_wallet_vetting(
                    addr,
                    bot_score=result.get("bot_score"),
                    unresolved_exposure_usd=None,
                    total_pnl=result.get("total_pnl"),
                    roi_pct=result.get("roi_pct"),
                    conviction_score=result.get("conviction_score"),
                    is_specialty=result.get("is_specialty", False),
                    specialty_note=result.get("specialty_note"),
                    specialty_market_id=result.get("specialty_market_id"),
                    specialty_category=result.get("specialty_category"),
                )
            print(f"[+] Added: {wallet.nickname} ({wallet.address[:10]}...)")
            added += 1
        else:
            skipped += 1

    print(f"\nAdded: {added} | Already existed: {skipped} | Rejected (vet): {rejected}")


def show_portfolio(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Show a wallet's portfolio."""
    address = args.address.strip()
    portfolio = storage.get_portfolio(address, api_factory)

    if not portfolio:
        print(f"[-] Wallet not found: {address}")
        return

    print(f"\nPortfolio for {portfolio.nickname} ({portfolio.address[:10]}...)")
    print(f"Total Value: ${portfolio.total_value:,.2f}\n")

    if not portfolio.positions:
        print("No open positions.")
        return

    print(f"{'Market':<50} {'Outcome':<10} {'Shares':<10} {'Value'}")
    print("-" * 80)

    for pos in portfolio.positions:
        market = pos.market[:48]
        print(f"{market:<50} {pos.outcome:<10} {pos.shares:<10.2f} ${pos.value:,.2f}")


def show_history(args, storage: WalletStorage, config: Config):
    """Show the performance history of a wallet."""
    address = args.address.strip()
    history = storage.get_wallet_history(address)
    if not history:
        print(f"No history found for {address}")
        return

    print(f"\nPerformance history for {address}:")
    print(f"{'Timestamp':<26} {'Win Rate':<12} {'Trades':<10} {'Volume'}")
    print("-" * 60)

    for entry in history:
        print(
            f"{entry['timestamp']:<26} {entry['win_rate']:>6.1f}%    {entry['wins']}/{entry['total_trades']:<7} ${entry['total_volume']:,.0f}"
        )


def handle_jupiter_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle Jupiter commands."""
    jupiter_client = api_factory.get_jupiter_client()

    if args.action == "quote":
        if not args.input_mint or not args.output_mint or not args.amount:
            print(
                "Usage: python main.py jupiter quote --input-mint <mint> --output-mint <mint> --amount <amount>"
            )
            print(
                "Example: python main.py jupiter quote --input-mint So11111111111111111111111111111111111111112 --output-mint EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v --amount 1"
            )
            return

        quote = jupiter_client.get_quote(args.input_mint, args.output_mint, args.amount)
        if quote:
            print(quote)
        else:
            print("Could not get quote.")

    elif args.action == "swap":
        print("Swap functionality not yet implemented.")


def handle_jupiter_price_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle Jupiter price commands."""
    price_client = api_factory.get_jupiter_price_client()

    if not args.mints:
        print("Usage: python main.py jupiter-price --mints <mint1>,<mint2>,...")
        print(
            "Example: python main.py jupiter-price --mints So11111111111111111111111111111111111111112,EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )
        return

    mints = [m.strip() for m in args.mints.split(",")]
    prices = price_client.get_prices_dict(mints)

    if prices:
        print("Token Prices:")
        for mint, price in prices.items():
            print(f"  {mint}: ${price:.6f}")
    else:
        print("Could not fetch prices.")


def handle_jupiter_portfolio_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle Jupiter portfolio commands."""
    portfolio_client = api_factory.get_jupiter_portfolio_client()

    if not args.address:
        print("Usage: python main.py jupiter-portfolio <wallet_address>")
        return

    summary = portfolio_client.get_portfolio_summary(args.address)

    print(f"Portfolio for {args.address}:")
    print(f"  SOL: {summary['sol']:.4f}")
    print(f"  Tokens: {summary['count']}")
    for token in summary["tokens"][:10]:
        mint = token.get("mint", "unknown")
        amount = token.get("amount", "0")
        print(f"    {mint}: {amount}")
    if summary["count"] > 10:
        print(f"    ... and {summary['count'] - 10} more")


def handle_jupiter_trigger_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle Jupiter trigger/limit order commands."""
    trigger_client = api_factory.get_jupiter_trigger_client()

    if args.action == "list":
        if not args.address:
            print("Usage: python main.py jupiter-trigger list <wallet_address>")
            return
        orders = trigger_client.get_active_orders(args.address)
        if orders:
            print(f"Active trigger orders for {args.address}:")
            for order in orders:
                print(
                    f"  {order.get('orderKey')}: {order.get('inputMint')} -> {order.get('outputMint')}"
                )
        else:
            print("No active trigger orders.")

    elif args.action == "history":
        if not args.address:
            print("Usage: python main.py jupiter-trigger history <wallet_address>")
            return
        orders = trigger_client.get_order_history(args.address)
        if orders:
            print(f"Trigger order history for {args.address}:")
            for order in orders:
                print(f"  {order.get('orderKey')}: {order.get('status')}")
        else:
            print("No order history.")

    else:
        print("Usage: python main.py jupiter-trigger <list|history> <wallet_address>")


def handle_jupiter_recurring_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle Jupiter recurring/DCA commands."""
    recurring_client = api_factory.get_jupiter_recurring_client()

    if args.action == "list":
        if not args.address:
            print("Usage: python main.py jupiter-recurring list <wallet_address>")
            return
        orders = recurring_client.get_active_orders(args.address)
        if orders:
            print(f"Active DCA orders for {args.address}:")
            for order in orders:
                print(
                    f"  {order.get('orderKey')}: {order.get('inputMint')} -> {order.get('outputMint')} every {order.get('frequency')}s"
                )
        else:
            print("No active DCA orders.")

    elif args.action == "history":
        if not args.address:
            print("Usage: python main.py jupiter-recurring history <wallet_address>")
            return
        orders = recurring_client.get_order_history(args.address)
        if orders:
            print(f"DCA order history for {args.address}:")
            for order in orders:
                print(f"  {order.get('orderKey')}: {order.get('status')}")
        else:
            print("No order history.")

    else:
        print("Usage: python main.py jupiter-recurring <list|history> <wallet_address>")


def handle_signals_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle signals command."""
    print("Signal generation not yet implemented.")


def handle_bot_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle bot command."""
    token = (config.telegram_bot_token or "").strip()
    if not token:
        print("[-] Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env")
        return
    bot = TelegramBot(token, storage, config, api_factory)
    bot.run()


def handle_discord_command(
    args, storage: WalletStorage, config: Config, api_factory=None
):
    """Handle discord command."""
    token = (config.discord_bot_token or "").strip()
    if not token:
        print("[-] Discord not configured. Set discord_bot_token in .env")
        return
    bot = DiscordBot(token, storage, config, api_factory)
    bot.run_bot()


def handle_dashboard_command(args, storage: WalletStorage, config: Config):
    """Handle dashboard command."""
    socketio = SocketIO()
    dash = Dashboard(storage, socketio)
    dash.run()


def handle_all_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Start everything: monitor, Telegram bot, Discord bot, and dashboard."""
    import threading

    # Start dashboard in background
    socketio = SocketIO()
    dash = Dashboard(storage, socketio)

    def run_dashboard():
        dash.run()

    dash_thread = threading.Thread(target=run_dashboard, daemon=True, name="Dashboard")
    dash_thread.start()
    print("[*] Dashboard started - http://127.0.0.1:5000 (or configured port)")

    # Run monitor (starts Telegram + Discord in background, then main loop)
    monitor(args, storage, config, api_factory)


def handle_check_positions_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle check_positions command."""
    alerter = PositionAlerter()
    wallets = storage.list_wallets()
    alerter.check_positions(wallets)
    print("Checked for position changes.")


def handle_vet_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle vet command - vet wallets for bots and P&L cheaters."""
    vetter = WalletVetting(api_factory)
    min_bet = args.min_bet if args.min_bet else config.min_bet_size

    if args.address:
        addresses = [args.address]
    else:
        wallets = storage.list_wallets()
        addresses = [w.address for w in wallets]

    print(f"Vetting {len(addresses)} wallet(s) (min bet: ${min_bet})...\n")

    for addr in addresses:
        result = vetter.vet_wallet(addr, min_bet)
        if not result:
            print(f"[-] {addr}: No trading data")
            continue

        status = "✅ PASSED" if result["passed"] else "❌ FAILED"
        print(f"{result['address'][:12]}... {status}")
        print(f"   Win rate (real): {result['win_rate_real']:.1f}%")
        print(f"   Avg bet size: ${result['avg_bet_size']:.2f}")
        print(f"   Total trades: {result['total_trades']}")
        print(f"   Resolved markets: {result['resolved_markets_traded']}")
        print(f"   Bot score: {result['bot_score']}%")
        print(f"   Unsettled losses: {result['unsettled_loses']}")
        print(
            f"   Wins/Losses: {result.get('total_wins', 0)}/{result.get('total_losses', 0)}"
        )
        if "total_pnl" in result:
            print(
                f"   PnL: ${result.get('total_pnl', 0):.2f} | ROI: {result.get('roi_pct', 0):.1f}% | Conviction: {result.get('conviction_score', 0):.1f} | Trades/day: {result.get('trades_per_day', 0):.1f}"
            )
        if result.get("estimated_fees_paid", 0) > 0:
            print(f"   Est. fees paid: ${result.get('estimated_fees_paid', 0):.2f}")
        if result.get("specialty_or_hot_streak_note"):
            print(f"   {result['specialty_or_hot_streak_note']}")
        if result["issues"]:
            print(f"   Issues: {', '.join(result['issues'])}")
        # Persist vetting results (Phase 2) - only if wallet is tracked
        if storage.get_wallet(addr):
            storage.update_wallet_vetting(
                addr,
                bot_score=result.get("bot_score"),
                unresolved_exposure_usd=None,
                total_pnl=result.get("total_pnl"),
                roi_pct=result.get("roi_pct"),
                conviction_score=result.get("conviction_score"),
                is_specialty=result.get("is_specialty", False),
                specialty_note=result.get("specialty_note"),
                specialty_market_id=result.get("specialty_market_id"),
                specialty_category=result.get("specialty_category"),
            )
        print()


def handle_leaders_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Show top vetted traders by reliability score or current streak."""
    mode = (getattr(args, "mode", "reliable") or "reliable").lower()
    limit = int(getattr(args, "limit", 10) or 10)
    limit = max(1, min(limit, 50))

    vetting_path = Path("data/vetted_leaderboard.json")
    if not vetting_path.exists():
        print("No vetted leaderboard found. Run monitor/background vetting first.")
        return

    try:
        with open(vetting_path) as f:
            data = json.load(f)
        wallets = data.get("wallets", []) or []
    except Exception as e:
        print(f"Failed reading vetted leaderboard: {e}")
        return

    if not wallets:
        print("No vetted wallets available.")
        return

    if mode == "streak":
        wallets.sort(
            key=lambda w: (
                float(w.get("current_win_streak", 0) or 0),
                float(w.get("recent_win_rate", 0) or 0),
                float(w.get("reliability_score", 0) or 0),
                float(w.get("win_rate_real", 0) or 0),
            ),
            reverse=True,
        )
        title = f"Top {limit} vetted traders by WIN STREAK"
    else:
        wallets.sort(
            key=lambda w: (
                float(w.get("reliability_score", 0) or 0),
                float(w.get("recent_win_rate", 0) or 0),
                float(w.get("current_win_streak", 0) or 0),
                float(w.get("win_rate_real", 0) or 0),
                float(w.get("avg_bet_size", 0) or 0),
            ),
            reverse=True,
        )
        title = f"Top {limit} vetted traders by RELIABILITY"

    print(title)
    print("-" * len(title))
    for i, w in enumerate(wallets[:limit], 1):
        name = w.get("nickname") or (w.get("address", "")[:12] + "...")
        wr = float(w.get("win_rate_real", 0) or 0)
        rwr = float(w.get("recent_win_rate", 0) or 0)
        streak = int(w.get("current_win_streak", 0) or 0)
        rel = float(w.get("reliability_score", 0) or 0)
        cat = (w.get("top_category") or "—").lower()
        print(
            f"{i:>2}. {name} | Rel {rel:>5.1f} | Streak {streak:>2} | Win {wr:>5.1f}% | Recent {rwr:>5.1f}% | Top {cat}"
        )


def handle_check_odds_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle check_odds command."""
    alerter = OddsAlerter()
    markets = []
    alerter.check_odds(markets)
    print("Checked for odds movement.")


def handle_test_webhook_command(args, storage: WalletStorage, config: Config):
    """Handle test-webhook command - send a test message to Discord."""
    webhook_url = config.discord_webhook_url
    if not webhook_url:
        print("[-] Discord webhook not configured. Set discord_webhook_url in .env")
        return

    dispatcher = AlertDispatcher(webhook_url, cooldown_seconds=0)
    test_payload = {
        "embeds": [
            {
                "title": "🧪 PolySuite Test",
                "description": "Discord webhook is working correctly!",
                "color": 0x3B82F6,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]
    }

    success = dispatcher.send_webhook(test_payload)
    if success:
        print("[+] Test message sent successfully!")
    else:
        print("[-] Failed to send test message. Check your webhook URL.")


def handle_events_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle events command - check for market events."""
    from src.alerts.events import EventAlerter

    alerter = EventAlerter(
        api_factory,
        new_market_hours=config.new_market_alert_hours,
        volume_spike_multiplier=config.volume_spike_multiplier,
        odds_move_threshold=config.odds_move_threshold,
    )

    print(alerter.get_summary())


def handle_ask_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle ask command (disabled in alert-first mode)."""
    print(
        "Chat AI is disabled for performance. Use your external AI agent; "
        "PolySuite AI remains focused on alert logic."
    )


def setup_argument_parser():
    """Setup and return the argument parser."""
    parser = argparse.ArgumentParser(description="PolySuite - Polymarket Tracker")
    parser.add_argument("--config", default="config.json", help="Config file path")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add wallet
    add_p = subparsers.add_parser("add", help="Add a wallet to track")
    add_p.add_argument("address", help="Wallet address (0x...)")
    add_p.add_argument("nickname", help="Nickname for this wallet")

    # Remove wallet
    rem_p = subparsers.add_parser("remove", help="Remove a wallet")
    rem_p.add_argument("address", help="Wallet address")

    # List wallets
    list_p = subparsers.add_parser("list", help="List tracked wallets")
    list_p.add_argument(
        "--by-category", action="store_true", help="Show win rate by category"
    )
    list_p.add_argument("--min-trades", type=int, help="Minimum number of trades")
    list_p.add_argument("--min-volume", type=int, help="Minimum trade volume")
    list_p.add_argument(
        "--min-recent-trades", type=int, help="Minimum number of recent trades"
    )
    list_p.add_argument(
        "--recent-days", type=int, default=7, help="Number of days to consider recent"
    )

    # Refresh
    ref_p = subparsers.add_parser("refresh", help="Refresh wallet stats")
    ref_p.add_argument("address", help="Wallet address (or 'all')")

    # Monitor
    subparsers.add_parser("monitor", help="Run continuous monitoring")

    # Check convergence
    subparsers.add_parser("check", help="Check for convergences once")

    # Markets
    mk_p = subparsers.add_parser("markets", help="List active markets")
    mk_p.add_argument("--limit", type=int, default=20, help="Number to show")

    # Import from leaderboard
    imp_p = subparsers.add_parser("import", help="Import top traders from leaderboards")
    imp_p.add_argument("--limit", type=int, default=10, help="Traders per leaderboard")

    # Show portfolio
    port_p = subparsers.add_parser("portfolio", help="Show a wallet's portfolio")
    port_p.add_argument("address", help="Wallet address")

    # Show history
    hist_p = subparsers.add_parser(
        "history", help="Show a wallet's performance history"
    )
    hist_p.add_argument("address", help="Wallet address")

    # Jupiter
    jup_p = subparsers.add_parser("jupiter", help="Interact with Jupiter API")
    jup_p.add_argument("action", choices=["quote", "swap"], help="Action to perform")
    jup_p.add_argument("--input-mint", help="Input token mint address")
    jup_p.add_argument("--output-mint", help="Output token mint address")
    jup_p.add_argument("--amount", type=int, help="Amount to swap")

    # Jupiter Price
    price_p = subparsers.add_parser(
        "jupiter-price", help="Get token prices from Jupiter"
    )
    price_p.add_argument("--mints", help="Comma-separated list of token mint addresses")

    # Jupiter Portfolio
    port_p = subparsers.add_parser(
        "jupiter-portfolio", help="Get wallet holdings from Jupiter"
    )
    port_p.add_argument("address", help="Wallet address")

    # Jupiter Trigger (Limit Orders)
    trig_p = subparsers.add_parser(
        "jupiter-trigger", help="Manage trigger/limit orders"
    )
    trig_p.add_argument("action", choices=["list", "history"], help="Action to perform")
    trig_p.add_argument("address", help="Wallet address", nargs="?")

    # Jupiter Recurring (DCA)
    rec_p = subparsers.add_parser(
        "jupiter-recurring", help="Manage recurring/DCA orders"
    )
    rec_p.add_argument("action", choices=["list", "history"], help="Action to perform")
    rec_p.add_argument("address", help="Wallet address", nargs="?")

    # Signals
    subparsers.add_parser("signals", help="Generate trading signals")

    # Bot
    subparsers.add_parser("bot", help="Start the Telegram bot")

    # Discord
    subparsers.add_parser("discord", help="Start the Discord bot")

    # Dashboard
    subparsers.add_parser("dashboard", help="Start the web dashboard")

    # All (monitor + bots + dashboard)
    subparsers.add_parser(
        "all", help="Start everything: monitor, Telegram, Discord, dashboard"
    )

    # Position Alerts
    subparsers.add_parser("check_positions", help="Check for position changes")

    # Odds Movement
    subparsers.add_parser("check_odds", help="Check for odds movement")

    # Test Webhook
    subparsers.add_parser("test-webhook", help="Send a test message to Discord")

    # Events
    subparsers.add_parser(
        "events",
        help="Check for market events (new markets, volume spikes, odds moves)",
    )

    # Backtest
    backtest_p = subparsers.add_parser(
        "backtest", help="Backtest alert log (historical)"
    )
    backtest_p.add_argument("action", choices=["replay"], help="Action to perform")
    backtest_p.add_argument(
        "--fee-bps", type=float, default=30, help="Fee in basis points (default 30)"
    )

    # Vet wallets
    vet_p = subparsers.add_parser("vet", help="Vet wallets for bots and P&L cheaters")
    vet_p.add_argument(
        "address", nargs="?", help="Wallet address (or all tracked if omitted)"
    )
    vet_p.add_argument("--min-bet", type=float, help="Minimum average bet size")

    # Leaders (vetted rankings)
    leaders_p = subparsers.add_parser(
        "leaders", help="Top vetted traders by reliability or streak"
    )
    leaders_p.add_argument(
        "--mode",
        choices=["reliable", "streak"],
        default="reliable",
        help="Ranking mode",
    )
    leaders_p.add_argument(
        "--limit", type=int, default=10, help="Number of wallets to show (1-50)"
    )

    # Ask agent (disabled; kept for backward compatibility)
    ask_p = subparsers.add_parser("ask", help="(Disabled) In-app chat AI")
    ask_p.add_argument("question", nargs="*", help="Ignored")
    ask_p.add_argument("--model", default="llama3.2", help="Ignored")

    return parser


def main():
    """Main CLI entry point."""
    parser = setup_argument_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print("\nExamples:")
        print("  python main.py add 0x123... BigTrader")
        print("  python main.py list")
        print("  python main.py refresh all")
        print("  python main.py check")
        print("  python main.py monitor")
        print("  python main.py all    # Start everything")
        print("  python main.py history 0x123...")
        return

    # Initialize core components
    config = Config(args.config)
    storage = WalletStorage()
    api_factory = APIClientFactory(config)

    # Command mapping
    command_map = {
        "add": add_wallet,
        "remove": remove_wallet,
        "list": list_wallets,
        "refresh": refresh_wallet,
        "monitor": monitor,
        "check": check_convergence,
        "markets": list_markets,
        "import": import_leaderboard,
        "portfolio": show_portfolio,
        "history": show_history,
        "jupiter": handle_jupiter_command,
        "jupiter-price": handle_jupiter_price_command,
        "jupiter-portfolio": handle_jupiter_portfolio_command,
        "jupiter-trigger": handle_jupiter_trigger_command,
        "jupiter-recurring": handle_jupiter_recurring_command,
        "signals": handle_signals_command,
        "bot": handle_bot_command,
        "discord": handle_discord_command,
        "dashboard": handle_dashboard_command,
        "all": handle_all_command,
        "check_positions": handle_check_positions_command,
        "check_odds": handle_check_odds_command,
        "test-webhook": handle_test_webhook_command,
        "events": handle_events_command,
        "ask": handle_ask_command,
        "vet": handle_vet_command,
        "leaders": handle_leaders_command,
    }

    # Dependency mapping
    dependencies = {
        "add": [storage, config],
        "remove": [storage, config],
        "list": [storage, config, api_factory],
        "refresh": [storage, config, api_factory],
        "monitor": [storage, config, api_factory],
        "check": [storage, config, api_factory],
        "markets": [storage, config, api_factory],
        "import": [storage, config, api_factory],
        "portfolio": [storage, config, api_factory],
        "history": [storage, config],
        "jupiter": [storage, config, api_factory],
        "jupiter-price": [storage, config, api_factory],
        "jupiter-portfolio": [storage, config, api_factory],
        "jupiter-trigger": [storage, config, api_factory],
        "jupiter-recurring": [storage, config, api_factory],
        "signals": [storage, config, api_factory],
        "bot": [storage, config, api_factory],
        "discord": [storage, config, api_factory],
        "dashboard": [storage, config],
        "all": [storage, config, api_factory],
        "check_positions": [storage, config, api_factory],
        "check_odds": [storage, config, api_factory],
        "test-webhook": [storage, config],
        "ask": [storage, config, api_factory],
        "events": [storage, config, api_factory],
        "vet": [storage, config, api_factory],
        "leaders": [storage, config, api_factory],
    }

    # Execute command (single path - no duplicate execution)
    command_func = command_map.get(args.command)
    if not command_func:
        parser.print_help()
        print("  python main.py add 0x123... BigTrader")
        print("  python main.py list")
        print("  python main.py refresh all")
        print("  python main.py check")
        print("  python main.py monitor")
        print("  python main.py all    # Start everything")
        print("  python main.py history 0x123...")
        return

    # Start TaskManager only for long-running commands
    task_manager = None
    long_running = {"monitor", "bot", "discord", "all"}
    if args.command in long_running:
        task_manager = TaskManager(api_factory)
        task_manager.start()

    try:
        deps = dependencies.get(args.command, [])
        if args.command == "refresh" and getattr(args, "address", "").lower() == "all":
            refresh_all(args, *deps)
        else:
            command_func(args, *deps)
    finally:
        if task_manager:
            task_manager.stop()
        api_factory.close()


if __name__ == "__main__":
    main()
