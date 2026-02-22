"""Main entry point for PolySuite CLI."""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask_socketio import SocketIO

from src.alerts import AlertDispatcher
from src.alerts.arbitrage import ArbitrageDetector
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
from src.tasks import TaskManager
from src.telegram_bot import TelegramBot
from src.wallet import Wallet
from src.wallet.calculator import WalletCalculator
from src.wallet.storage import WalletStorage


def add_wallet(args, storage: WalletStorage, _config: Config):
    """Add a new wallet to track."""
    # Check max wallets
    wallets = storage.list_wallets()
    if len(wallets) >= 10:
        print("Maximum 10 wallets allowed. Remove one first.")
        return

    try:
        storage.add_wallet(args.address, args.nickname)
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
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
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


def monitor(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Run continuous monitoring mode with convergence detection."""
    print("Starting PolySuite monitor...")
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

    # Use combined dispatcher for simultaneous Discord + Telegram alerts
    from src.alerts.combined import CombinedDispatcher

    combined = CombinedDispatcher(config)

    telegram = TelegramDispatcher(config.telegram_bot_token, config.telegram_chat_id)
    detector = ConvergenceDetector(
        storage,
        threshold=config.win_rate_threshold,
        time_window_hours=config.convergence_time_window_hours,
        max_market_age_hours=config.convergence_max_market_age_hours,
        early_entry_minutes=config.convergence_early_entry_minutes,
    )
    arb_detector = ArbitrageDetector(api_factory)
    discovery = MarketDiscovery(api_factory, config.tracked_categories)
    leaderboard_importer = LeaderboardImporter(api_factory)
    smart_money_detector = SmartMoneyDetector(api_factory)

    from src.alerts.events import EventAlerter

    event_alerter = EventAlerter(
        api_factory,
        new_market_hours=config.new_market_alert_hours,
        volume_spike_multiplier=config.volume_spike_multiplier,
    )

    calculator = WalletCalculator(api_factory)

    # Track markets we've alerted on
    alerted_markets: set = set()
    alerted_arbs: set = set()  # Track alerted arbitrage opps

    # Track last imports
    last_smart_money_import = 0  # Import immediately on first run
    import_interval = config.leaderboard_import_interval
    last_arb_check = 0
    arb_check_interval = 60  # Check arbitrage every 1 minute (was 5)

    # Health check / heartbeat
    last_health_check = 0
    health_check_interval = 120  # Every 2 minutes

    # Database backup
    last_backup = 0
    backup_interval = 21600  # Every 6 hours

    # Alert check intervals - more aggressive
    new_market_check_interval = 60  # Check for new markets every 1 min
    volume_check_interval = 30  # Check volume every 30 seconds
    odds_check_interval = 60  # Check odds every 1 min
    last_new_market_check = 0
    last_volume_check = 0
    last_odds_check = 0

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

    while True:
        try:
            import traceback

            current_time = time.time()

            # Send test alert on first run
            if last_health_check == 0:
                test_msg = "✅ PolySuite started! Bot is running."
                combined.send_health(test_msg)
                print(f"[*] Sent startup alert to Discord & Telegram")

            # Send health check
            if current_time - last_health_check > health_check_interval:
                health_msg = f"HEARTBEAT - PolySuite running. Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                combined.send_health(health_msg)
                last_health_check = current_time

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

            # Simple whale trade alerts - check tracked wallets for new positions
            # No leaderboard import - users add wallets they want to track
            if current_time - last_smart_money_import > 60:  # Check every minute
                print("\n[*] Checking tracked wallets for new trades...")

                wallets = storage.list_wallets()
                pm = api.get_polymarket_api()

                for wallet in wallets:
                    try:
                        # Get current positions
                        positions = pm.get_wallet_positions(wallet.address) or []

                        # Check for new positions (simple comparison)
                        last_pos = getattr(wallet, "_last_positions", [])
                        last_mids = set(str(p.get("market_id", "")) for p in last_pos)
                        curr_mids = set(str(p.get("market_id", "")) for p in positions)

                        new_markets = curr_mids - last_mids

                        if new_markets and len(new_markets) > 0:
                            # Alert on whale trade
                            for pos in positions:
                                mid = str(pos.get("market_id", ""))
                                if mid in new_markets:
                                    q = pos.get("question", "Unknown")[:35]
                                    side = pos.get("side", "?")
                                    size = float(pos.get("size", 0) or 0)

                                    emoji = "🐋"
                                    msg = f"\n{emoji} WHALE: {wallet.nickname} {side.upper()} ${size:,.0f}\n{q}"
                                    combined.send_health(msg)
                                    print(msg)

                            # Store current as last
                            wallet._last_positions = positions

                    except Exception as e:
                        pass

                last_smart_money_import = current_time

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

            # ===== PRIORITY 1: NEW EVENTS (1hr) - ALWAYS ALERT, CHECK ARB FIRST =====
            print("\n[*] Checking for new events...")
            new_events = event_alerter.check_new_events(hours=1, limit=50)
            for event in new_events:
                event_id = event.get("id")
                if not event_id:
                    continue

                # Check arbitrage BEFORE alerting
                arb = arb_detector.check_market_arb(event_id)
                try:
                    profit = float(arb.get("profit_pct", 0)) if arb else 0
                except (ValueError, TypeError):
                    profit = 0

                if profit >= 0.5:
                    # Has arbitrage - color code and indicate
                    if profit >= 1.5:
                        emoji = "🟢"
                    elif profit >= 1.0:
                        emoji = "🔵"
                    else:
                        emoji = "🟠"
                    msg = f"\n🆕💰 NEW EVENT + ARB {emoji}({profit:.2f}%): {event.get('question', '')[:40]}"
                    # Send BOTH alerts
                    combined.send_new_market(event)
                    combined.send_arb(arb)
                else:
                    # No arbitrage - just new event
                    msg = f"\n🆕 NEW EVENT: {event.get('question', '')[:50]}"
                    combined.send_new_market(event)

                print(msg)
                alerted_arbs.add(f"new_{event_id}")

            # ===== PRIORITY 2: CRYPTO REAL PRICES (CoinGecko) - EVERY SCAN =====
            print("[*] Checking crypto prices...")
            crypto_alerts = event_alerter.check_crypto_prices()
            for move in crypto_alerts:
                direction = move.get("direction", "up")
                emoji = "🚀" if direction == "up" else "📉"
                symbol = move.get("symbol", "CRYPTO")
                price = move.get("price", 0)
                change = move.get("change_24h", 0)
                msg = f"\n{emoji} CRYPTO: {symbol} ${price:,.0f} ({change:+.1f}%)"
                combined.send_health(msg)
                print(msg)

            # Also check Polymarket crypto moves
            crypto_moves = event_alerter.check_crypto_moves()
            for move in crypto_moves:
                direction = move.get("direction", "up")
                emoji = "🚀" if direction == "up" else "📉"
                try:
                    move_pct = float(move.get("move_pct", 0))
                    price = float(move.get("price", 0))
                except (ValueError, TypeError):
                    move_pct = 0
                    price = 0
                msg = f"\n{emoji} POLY CRYPTO: {move.get('question', '')[:35]} {move_pct:.1f}%"
                combined.send_health(msg)
                print(msg)

            # ===== PRIORITY 3: SPORTS/GAMES EXPIRING SOON =====
            print("[*] Checking expiring events...")
            expiring = event_alerter.check_expiring_events(hours=2, limit=20)
            for event in expiring:
                try:
                    hours_left = float(event.get("hours_left", 0))
                except (ValueError, TypeError):
                    hours_left = 0
                urgency = (
                    "🔴" if hours_left < 0.5 else ("🟠" if hours_left < 1 else "🔵")
                )
                msg = f"\n{urgency}⏰ EXPIRING SOON: {event.get('question', '')[:40]} ({hours_left:.1f}h left)"
                combined.send_health(msg)
                print(msg)

            # ===== PRIORITY 4: CONVERGENCE (tracked wallets in same event) =====
            print("[*] Checking convergence...")
            convergences = detector.find_convergences(min_wallets=2)
            new_convergences = [
                c for c in convergences if c["market_id"] not in alerted_markets
            ]

            for conv in new_convergences:
                market = conv.get("market_info") or {}
                wallets = conv.get("wallets", [])

                urgency = (
                    "CRITICAL"
                    if conv.get("has_early_entry") and len(wallets) >= 3
                    else (
                        "HIGH"
                        if conv.get("has_early_entry") or len(wallets) >= 3
                        else "NORMAL"
                    )
                )
                emoji = (
                    "🔴"
                    if urgency == "CRITICAL"
                    else ("🟠" if urgency == "HIGH" else "🔵")
                )

                msg = f"\n{emoji} CONVERGENCE: {len(wallets)} traders in {market.get('question', 'Unknown')[:40]}..."

                combined.send_convergence(
                    market=market,
                    wallets=wallets,
                    threshold=config.win_rate_threshold,
                    convergence=conv,
                )
                print(msg)
                alerted_markets.add(conv["market_id"])

            # ===== FULL MARKET SCANS (arbitrage, volume, odds) - CAN RUN IN ANY ORDER =====

            # Check arbitrage on ALL markets
            if current_time - last_arb_check > arb_check_interval:
                print("[*] Checking arbitrage (all markets)...")
                arb_opps = arb_detector.get_top_opportunities(limit=10)
                for arb in arb_opps:
                    market_id = arb.get("market_id") or arb.get("condition_id")
                    if market_id and market_id not in alerted_arbs:
                        try:
                            profit = float(arb.get("profit_pct", 0))
                        except (ValueError, TypeError):
                            profit = 0
                        # Color code: 0.5% orange, 1% blue, 1.5%+ green
                        if profit >= 1.5:
                            emoji = "🟢"
                        elif profit >= 1.0:
                            emoji = "🔵"
                        else:
                            emoji = "🟠"

                        msg = f"\n{emoji}💰 ARBITRAGE ({profit:.2f}%): YES ${arb['yes_price']:.2f} NO ${arb['no_price']:.2f}"
                        combined.send_arb(arb)
                        print(msg)
                        alerted_arbs.add(market_id)
                last_arb_check = current_time

            # Check volume spikes
            print("[*] Checking volume spikes...")
            volume_spikes = event_alerter.check_volume_spikes(limit=10)
            for spike in volume_spikes[:3]:
                try:
                    vol_ratio = float(spike.get("volume_ratio", 0))
                except (ValueError, TypeError):
                    vol_ratio = 0
                msg = f"\n📈 VOLUME SPIKE: {spike.get('question', 'Unknown')[:40]} ({vol_ratio:.1f}x)"
                combined.send_health(msg)
                print(msg)

            # Check odds movements
            odds_moves = event_alerter.check_odds_movements(limit=10)
            for move in odds_moves[:2]:
                try:
                    move_pct = float(move.get("move_pct", 0))
                except (ValueError, TypeError):
                    move_pct = 0
                msg = f"\n📊 ODDS MOVE: {move.get('question', '')[:40]} {move_pct:.1f}%"
                combined.send_health(msg)
                print(msg)

            # ===== PRIORITY 2: CRYPTO 15m/5m UP/DOWN - EVERY SCAN =====
            print("[*] Checking crypto price moves...")
            crypto_moves = event_alerter.check_crypto_moves()
            for move in crypto_moves:
                try:
                    move_pct = float(move.get("move_pct", 0))
                    price = float(move.get("price", 0))
                except (ValueError, TypeError):
                    move_pct = 0
                    price = 0
                msg = f"\n{'🚀' if move.get('direction') == 'up' else '📉'} CRYPTO {move.get('timeframe')}: {move.get('symbol')} {move_pct:.1f}% ${price}"
                combined.send_health(msg)
                print(msg)

            # ===== PRIORITY 3: SPORTS/GAMES EXPIRING SOON =====
            print("[*] Checking expiring events...")
            expiring = event_alerter.check_expiring_events(hours=2, limit=20)
            for event in expiring:
                event_id = event.get("id")
                try:
                    hours_left = float(event.get("hours_left", 0))
                except (ValueError, TypeError):
                    hours_left = 0
                msg = f"\n⏰ EXPIRING SOON: {event.get('question', '')[:40]} ({hours_left:.1f}h left)"
                combined.send_health(msg)
                print(msg)

            # ===== PRIORITY 4: CONVERGENCE (tracked wallets in same event) =====
            print("[*] Checking convergence...")
            convergences = detector.find_convergences(min_wallets=2)
            new_convergences = [
                c for c in convergences if c["market_id"] not in alerted_markets
            ]

            for conv in new_convergences:
                market = conv.get("market_info") or {}
                wallets = conv.get("wallets", [])

                urgency = (
                    "CRITICAL"
                    if conv.get("has_early_entry") and len(wallets) >= 3
                    else (
                        "HIGH"
                        if conv.get("has_early_entry") or len(wallets) >= 3
                        else "NORMAL"
                    )
                )
                emoji = (
                    "🔴"
                    if urgency == "CRITICAL"
                    else ("🟠" if urgency == "HIGH" else "🔵")
                )

                msg = f"\n{emoji} {urgency} CONVERGENCE: {len(wallets)} traders in {market.get('question', 'Unknown')[:40]}..."

                combined.send_convergence(
                    market=market,
                    wallets=wallets,
                    threshold=config.win_rate_threshold,
                    convergence=conv,
                )
                print(msg)
                alerted_markets.add(conv["market_id"])

            # ===== PRIORITY 5: ARBITRAGE (on any market) =====
            if current_time - last_arb_check > arb_check_interval:
                print("[*] Checking arbitrage...")
                arb_opps = arb_detector.get_top_opportunities(limit=5)
                for arb in arb_opps:
                    market_id = arb.get("market_id") or arb.get("condition_id")
                    if market_id and market_id not in alerted_arbs:
                        try:
                            profit = float(arb.get("profit_pct", 0))
                        except (ValueError, TypeError):
                            profit = 0
                        if profit > 0.5:
                            msg = f"\n💰 ARBITRAGE: {profit:.2f}% - YES: ${arb['yes_price']:.2f} NO: ${arb['no_price']:.2f}"
                            combined.send_arb(arb)
                            print(msg)
                            alerted_arbs.add(market_id)
                last_arb_check = current_time

            # ===== PRIORITY 6: VOLUME SPIKES =====
            print("[*] Checking volume spikes...")
            volume_spikes = event_alerter.check_volume_spikes(limit=10)
            for spike in volume_spikes[:3]:
                try:
                    vol_ratio = float(spike.get("volume_ratio", 0))
                except (ValueError, TypeError):
                    vol_ratio = 0
                msg = f"\n📈 VOLUME SPIKE: {spike.get('question', 'Unknown')[:40]} ({vol_ratio:.1f}x)"
                combined.send_health(msg)
                print(msg)

            # ===== PRIORITY 7: ODDS MOVEMENTS =====
            odds_moves = event_alerter.check_odds_movements(limit=10)
            for move in odds_moves[:2]:
                try:
                    move_pct = float(move.get("move_pct", 0))
                except (ValueError, TypeError):
                    move_pct = 0
                msg = f"\n📊 ODDS MOVE: {move.get('question', '')[:40]} {move_pct:.1f}%"
                combined.send_health(msg)
                print(msg)

            # Clean old markets from alerted set
            active_markets = {
                m["id"] for m in polymarket_api.get_active_markets(limit=200) if m
            }
            alerted_markets = alerted_markets & active_markets

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
            except:
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
        print(f"{q:<50} ${v:>10,.0f}")


def import_leaderboard(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Import top traders from Polymarket leaderboards."""
    importer = LeaderboardImporter(api_factory)

    print("Fetching from Polymarket leaderboards...")
    traders = importer.fetch_leaderboard()

    if not traders:
        print("No traders found.")
        return

    print(f"\nFound {len(traders)} traders:\n")

    added = 0
    skipped = 0

    for i, trader in enumerate(traders, 1):
        addr = trader.get("address")
        if not addr:
            continue
        nickname = (
            trader.get("userName")
            or trader.get("username")
            or trader.get("proxyWallet", f"Trader{i}")[:10]
        )
        wallet = Wallet(address=addr, nickname=nickname)

        if storage.add_wallet(wallet):
            print(f"[+] Added: {wallet.nickname} ({wallet.address[:10]}...)")
            added += 1
        else:
            skipped += 1

    print(f"\nAdded: {added} | Already existed: {skipped}")


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
            return

        quote = jupiter_client.get_quote(args.input_mint, args.output_mint, args.amount)
        if quote:
            print(quote)
        else:
            print("Could not get quote.")

    elif args.action == "swap":
        print("Swap functionality not yet implemented.")


def handle_signals_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle signals command."""
    print("Signal generation not yet implemented.")


def handle_bot_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle bot command."""
    bot = TelegramBot(config.telegram_bot_token, storage, config, api_factory)
    bot.run()


def handle_discord_command(
    args, storage: WalletStorage, config: Config, api_factory=None
):
    """Handle discord command."""
    bot = DiscordBot(config.discord_bot_token, storage, config, api_factory)
    bot.run_bot()


def handle_dashboard_command(args, storage: WalletStorage, config: Config):
    """Handle dashboard command."""
    socketio = SocketIO()
    dash = Dashboard(storage, socketio)
    dash.run()


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
    from src.wallet.vetting import WalletVetting

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
        if result["issues"]:
            print(f"   Issues: {', '.join(result['issues'])}")
        print()


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
    """Handle ask command - query the Ollama agent."""
    from src.agent import Agent

    question = " ".join(args.question)
    agent = Agent(
        model=args.model, config=config, storage=storage, api_factory=api_factory
    )

    print(f"Q: {question}\n")
    response = agent.chat(question)
    print(response)


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

    # Signals
    subparsers.add_parser("signals", help="Generate trading signals")

    # Bot
    subparsers.add_parser("bot", help="Start the Telegram bot")

    # Discord
    subparsers.add_parser("discord", help="Start the Discord bot")

    # Dashboard
    subparsers.add_parser("dashboard", help="Start the web dashboard")

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

    # Vet wallets
    vet_p = subparsers.add_parser("vet", help="Vet wallets for bots and P&L cheaters")
    vet_p.add_argument(
        "address", nargs="?", help="Wallet address (or all tracked if omitted)"
    )
    vet_p.add_argument("--min-bet", type=float, help="Minimum average bet size")

    # Ask agent
    ask_p = subparsers.add_parser("ask", help="Ask the Ollama agent a question")
    ask_p.add_argument("question", nargs="+", help="Your question")
    ask_p.add_argument("--model", default="llama3.2", help="Ollama model to use")

    return parser


def main():
    """Main CLI entry point."""
    parser = setup_argument_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print("\nExamples:")

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
        "signals": handle_signals_command,
        "bot": handle_bot_command,
        "discord": handle_discord_command,
        "dashboard": handle_dashboard_command,
        "check_positions": handle_check_positions_command,
        "check_odds": handle_check_odds_command,
        "test-webhook": handle_test_webhook_command,
        "events": handle_events_command,
        "ask": handle_ask_command,
        "vet": handle_vet_command,
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
        "signals": [storage, config, api_factory],
        "bot": [storage, config, api_factory],
        "discord": [storage, config, api_factory],
        "dashboard": [storage, config],
        "check_positions": [storage, config, api_factory],
        "check_odds": [storage, config, api_factory],
        "test-webhook": [storage, config],
        "ask": [storage, config, api_factory],
        "events": [storage, config, api_factory],
        "vet": [storage, config, api_factory],
    }

    # Execute command
    command_func = command_map.get(args.command)
    if command_func:
        deps = dependencies.get(args.command, [])
        command_func(args, *deps)
    else:
        parser.print_help()
        print("  python main.py add 0x123... BigTrader")
        print("  python main.py list")
        print("  python main.py refresh all")
        print("  python main.py check")
        print("  python main.py monitor")
        print("  python main.py history 0x123...")
        return

    # Load config and storage
    config = Config(args.config)
    storage = WalletStorage()
    api_factory = APIClientFactory(config)
    task_manager = None

    try:
        # Start task manager
        task_manager = TaskManager(api_factory)
        task_manager.start()

        # Map commands to functions
        commands = {
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
            "signals": handle_signals_command,
            "bot": handle_bot_command,
            "discord": handle_discord_command,
            "dashboard": handle_dashboard_command,
            "check_positions": handle_check_positions_command,
            "check_odds": handle_check_odds_command,
        }

        # Commands that require the API factory
        needs_factory = {
            "monitor",
            "check",
            "markets",
            "import",
            "portfolio",
            "refresh",
            "jupiter",
            "signals",
            "check_positions",
            "check_odds",
            "bot",
            "ask",
            "vet",
            "events",
        }

        # Route commands
        if args.command == "refresh" and args.address.lower() == "all":
            refresh_all(args, storage, config, api_factory)
        elif args.command in commands:
            if args.command in needs_factory:
                commands[args.command](args, storage, config, api_factory)
            else:
                commands[args.command](args, storage, config)
        else:
            parser.print_help()
    finally:
        # Clean up
        if task_manager:
            task_manager.stop()
        api_factory.close()


if __name__ == "__main__":
    main()
