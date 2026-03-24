"""Main entry point for PolySuite CLI."""

import argparse
import logging
import sys
import os
import time

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.config.paths import DB_PATH

from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.wallet.calculator import WalletCalculator
from src.config import Config, max_tracked_wallets
from src.market.api import APIClientFactory
from src.market.discovery import MarketDiscovery
from src.alerts import AlertDispatcher
from src.alerts.convergence import ConvergenceDetector
from src.alerts.telegram import TelegramDispatcher
from src.discord_bot import DiscordBot
from src.telegram_bot import TelegramBot
from src.alerts.combined import CombinedDispatcher
from src.alerts.position import PositionAlerter
from src.alerts.odds import OddsAlerter
from src.analytics.smart_money import SmartMoneyDetector
from src.analytics.signals import SignalGenerator
from src.market.leaderboard import LeaderboardImporter
from src.tasks import TaskManager
from src.dashboard.app import Dashboard

def add_wallet(args, storage: WalletStorage, config: Config):
    """Add a new wallet to track."""
    cap = max_tracked_wallets(config)
    wallets = storage.list_wallets()
    if len(wallets) >= cap:
        print(f"Maximum {cap} wallets allowed (config wallet_discovery_max_wallets). Remove one first.")
        return

    try:
        wallet = Wallet(address=args.address, nickname=args.nickname)
        if storage.add_wallet(wallet):
            print(f"Added wallet {args.nickname} ({args.address})")
        else:
            print(f"Wallet {args.address} already exists.")
    except Exception as e:
        print(f"Error adding wallet: {e}")


def remove_wallet(args, storage: WalletStorage, config: Config):
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
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Refresh wallet stats from Polymarket."""
    address = args.address.strip()

    wallet = storage.get_wallet(address)
    if not wallet:
        print(f"[-] Wallet not found: {address}")
        return

    print(f"Refreshing {wallet.nickname}...")

    calculator = WalletCalculator(api_factory)
    total_trades, wins, win_rate, total_volume, resolved_n = (
        calculator.calculate_wallet_stats(address)
    )

    if total_trades > 0:
        storage.update_wallet_stats(
            address, total_trades, wins, total_volume, win_rate=win_rate
        )
        storage.log_wallet_history(wallet)
        print(
            f"[+] Updated: {win_rate:.1f}% on resolved ({wins}/{resolved_n} decisions), "
            f"{total_trades} fills, vol ~${total_volume}"
        )
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
        total_trades, wins, win_rate, total_volume, resolved_n = (
            calculator.calculate_wallet_stats(wallet.address)
        )
        if total_trades > 0:
            storage.update_wallet_stats(
                wallet.address,
                total_trades,
                wins,
                total_volume,
                win_rate=win_rate,
            )
            storage.log_wallet_history(wallet)
            print(
                f"[+] {wallet.nickname}: {win_rate:.1f}% resolved ({wins}/{resolved_n}), "
                f"{total_trades} fills"
            )
        else:
            print(f"- {wallet.nickname}: No trades")

    print("\n[+] All wallets refreshed")


def handle_refresh_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Dispatch refresh to single wallet or all."""
    if args.address.strip().lower() == "all":
        refresh_all(args, storage, config, api_factory)
    else:
        refresh_wallet(args, storage, config, api_factory)


def handle_profile_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Vet a wallet and print metrics for tuning config. Use with a known-good wallet."""
    from src.wallet.vetting import WalletVetting
    from src.utils import is_valid_address

    address = args.address.strip().lower()
    if not is_valid_address(address):
        print("[-] Invalid address format")
        return

    print(f"Profiling {address}... (vet + metrics for config tuning)\n")
    vetter = WalletVetting(api_factory, config=config)
    result = vetter.vet_wallet(address, min_bet=10, platform="polymarket")

    if not result:
        print("[-] No trades found or vetting failed")
        return

    wr = result.get("win_rate_real", 0)
    pnl = result.get("total_pnl", 0)
    roi = result.get("roi_pct", 0)
    wins = result.get("total_wins", 0)
    losses = result.get("total_losses", 0)
    trades = result.get("total_trades", 0)
    spec = result.get("specialty_category") or "(none)"
    passed = result.get("passed", False)
    issues = result.get("issues", [])

    print("--- Vet result ---")
    print(f"  passed:        {passed}")
    print(f"  win_rate:      {wr:.1f}%")
    print(f"  total_pnl:     ${pnl:,.2f}")
    print(f"  roi_pct:       {roi:.1f}%")
    print(f"  total_wins:    {wins}")
    print(f"  total_losses:  {losses}")
    print(f"  total_trades:  {trades}")
    print(f"  specialty:     {spec}")
    if issues:
        print(f"  issues:        {issues[:5]}")

    print("\n--- Config suggestions (set below these in config.json) ---")
    print(f"  wallet_cleanup_min_win_rate: {max(0, min(35, wr - 10))}  # keep wallets with WR >= this")
    if wins > 0:
        print(f"  vet_min_trades_won: 0  # or set to {max(0, wins - 5)} if you want min wins")
    if pnl > 0:
        print(f"  vet_min_pnl: 0  # or set to {pnl * 0.5:.0f} to require half this PnL")
    if roi > 0:
        print(f"  vet_min_roi_pct: 0  # or set to {max(0, roi - 5):.0f} to require similar ROI")
    print(f"  win_rate_threshold: 55  # high-performer badge; set to {max(50, wr - 5):.0f} to match this wallet")
    print("\nSee docs/WALLET_TUNING_GUIDE.md for full reference.")


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
    telegram = TelegramDispatcher(config.telegram_bot_token, config.telegram_chat_id)
    detector = ConvergenceDetector(
        wallet_storage=storage,
        threshold=config.win_rate_threshold,
        api_factory=api_factory,
        min_market_volume=float(config.get("convergence_min_volume", 5000) or 5000),
    )

    discovery = MarketDiscovery(api_factory, config.tracked_categories)
    leaderboard_importer = LeaderboardImporter(api_factory)
    smart_money_detector = SmartMoneyDetector(api_factory)
    position_detector = PositionAlerter()
    calculator = WalletCalculator(api_factory)

    # Track markets we've alerted on
    alerted_markets: set = set()
    alerted_arbs: set = set()  # Track alerted arbitrage opps

    # Track last imports
    last_smart_money_import = 0
    import_interval = config.leaderboard_import_interval

    # Execution order (priority): 1=Vetting (HIGH), 2=Alerts (MEDIUM), 3=Copy/Trade (LOW)
    while True:
        try:
            current_time = time.time()

            # ========== 1. VETTING (HIGH PRIORITY) ==========
            # Identify and flag smart money wallets
            if current_time - last_smart_money_import > import_interval:
                print("\n[*] Identifying smart money wallets...")
                smart_wallets = smart_money_detector.identify_smart_money()
                newly_flagged_wallets = []
                for wallet_address in smart_wallets:
                    wallet = storage.get_wallet(wallet_address)
                    if wallet and not wallet.is_smart_money:
                        if storage.flag_smart_money_wallet(wallet_address):
                            newly_flagged_wallets.append(wallet.to_dict())

                if newly_flagged_wallets:
                    print(
                        f"[+] Flagged {len(newly_flagged_wallets)} new smart money wallets"
                    )
                    dispatcher.send_smart_money_alert(newly_flagged_wallets)
                else:
                    print("[-] No new smart money wallets to flag")
                last_smart_money_import = current_time

            # Get high performers (vetting output used for alerts)
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

            # ========== 2. ALERTS (MEDIUM PRIORITY) ==========
            # Find convergences using detector
            convergences = detector.find_convergences(min_wallets=2)

            new_convergences = [
                c for c in convergences if c["market_id"] not in alerted_markets
            ]

            # Send alerts for new convergences
            for conv in new_convergences:
                market = conv.get("market_info") or {}
                wallets = conv.get("wallets", [])

                msg = f"\n🔥 CONVERGENCE: {len(wallets)} traders in {market.get('question', 'Unknown')[:50]}..."

                if has_discord:
                    success = dispatcher.send_convergence_alert(
                        market=market,
                        wallets=wallets,
                        threshold=config.win_rate_threshold,
                    )
                    msg += " [Discord [+]]" if success else " [Discord [-]]"

                if has_telegram:
                    success = telegram.send_convergence_alert(
                        market=market,
                        wallets=wallets,
                        threshold=config.win_rate_threshold,
                    )
                    msg += " [Telegram [+]]" if success else " [Telegram [-]]"

                print(msg)
                alerted_markets.add(conv["market_id"])

            # Check for new markets
            new_markets = discovery.check_for_new_markets()
            for market in new_markets:
                msg = f"\n🆕 New market: {market.get('question', 'Unknown')[:50]}"

                if has_discord:
                    dispatcher.send_new_market_alert(market)

                if has_telegram:
                    telegram.send_new_market_alert(market)

                print(msg)

            # Check for large positions
            for wallet in high_performers:
                large_positions = position_detector.check_for_large_positions(
                    wallet.address
                )
                for position in large_positions:
                    dispatcher.send_position_alert(position)

            # Clean old markets from alerted set
            active_markets = {
                m.get("id")
                for m in polymarket_api.get_active_markets(limit=200)
                if m.get("id")
            }
            alerted_markets = alerted_markets & active_markets

            # ========== 3. COPY / TRADE EXECUTION (LOW PRIORITY) ==========
            # Copy trading runs last when enabled (CopyEngine, RTDS)
            # Placeholder: copy execution would go here

            print(
                f"\rMonitoring {len(high_performers)} wallets | {len(convergences)} convergences",
                end="",
            )

            time.sleep(config.polling_interval)

        except KeyboardInterrupt:
            print("\n\nStopped.")
            break
        except Exception as e:
            print(f"\nError: {e}")
            time.sleep(5)


def check_convergence(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """One-time convergence check."""
    detector = ConvergenceDetector(
        wallet_storage=storage,
        threshold=config.win_rate_threshold,
        api_factory=api_factory,
        min_market_volume=float(config.get("convergence_min_volume", 5000) or 5000),
    )

    print(f"Checking for convergences (threshold: {config.win_rate_threshold}%)\n")

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
    traders = importer.import_all_polymarket(limit=args.limit)

    if not traders:
        print("No traders found.")
        return

    print(f"\nFound {len(traders)} traders:\n")

    added = 0
    skipped = 0

    for i, trader in enumerate(traders, 1):
        wallet = Wallet(
            address=trader["address"], nickname=trader.get("username", f"Trader{i}")
        )

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
    """Handle signals command - aggregates convergence, insider, contrarian, wallet signals."""
    generator = SignalGenerator(storage=storage, api_factory=api_factory, config=config)
    signals = generator.generate_signals()

    if not signals:
        print("No signals generated.")
        return

    print("\nGenerated Signals:")
    for signal in signals:
        stype = signal.get("type", "unknown")
        action = signal.get("action", "unknown")
        if "wallet" in signal:
            addr = signal["wallet"].get("address", "?")
            print(f"- [{stype}] {action}: {addr[:12]}...")
        elif "market_id" in signal:
            q = (signal.get("question") or "Unknown")[:50]
            print(f"- [{stype}] {action}: {q}...")
        else:
            print(f"- [{stype}] {action}")


def handle_bot_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle bot command."""
    token = config.telegram_bot_token
    if not token or not token.strip():
        print("Telegram bot token not configured. Skipping.")
        return
    bot = TelegramBot(token, storage)
    bot.run()


def handle_discord_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle discord command."""
    token = config.discord_bot_token
    if not token or not token.strip():
        print("Discord bot token not configured. Skipping.")
        return
    bot = DiscordBot(token, storage, config=config, api_factory=api_factory)
    bot.run_bot()


def handle_dashboard_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory = None
):
    """Dashboard only — no background collector. Scans run on-demand when buttons are clicked."""
    dash = Dashboard(storage, config=config, api_factory=None)
    dash.run(use_waitress=not getattr(args, "debug", False))


def handle_run_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Dashboard + background data collector. Scans run 1–2×/hr; buttons use cached data when available."""
    dash = Dashboard(storage, config=config, api_factory=api_factory)
    dash.run(use_waitress=not getattr(args, "debug", False))


def handle_check_positions_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle check_positions command."""
    alerter = PositionAlerter()
    wallets = storage.list_wallets()
    alerter.check_positions(wallets)
    print("Checked for position changes.")


def handle_check_odds_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle check_odds command."""
    alerter = OddsAlerter()
    # This is a placeholder for a more complex implementation
    markets = []
    alerter.check_odds(markets)
    print("Checked for odds movement.")


def handle_smart_money_command(
    args, storage: WalletStorage, config: Config, api_factory: APIClientFactory
):
    """Handle smart-money command."""
    smart_money_detector = SmartMoneyDetector(api_factory)
    print("[*] Identifying smart money wallets...")
    smart_wallets = smart_money_detector.identify_smart_money()
    if smart_wallets:
        print(f"[+] Found {len(smart_wallets)} smart money wallets:")
        for wallet in smart_wallets:
            print(f"- {wallet}")
    else:
        print("[-] No smart money wallets found.")


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
    p_dash = subparsers.add_parser("dashboard", help="Start the web dashboard")
    p_dash.add_argument("--debug", action="store_true", help="Use Flask dev server (hot reload) instead of Waitress")
    # Run (dashboard + background data collector — scan buttons use cached data)
    p_run = subparsers.add_parser("run", help="Run dashboard with background data collector (insider, convergence, contrarian)")
    p_run.add_argument("--debug", action="store_true", help="Use Flask dev server (hot reload) instead of Waitress")

    # Position Alerts
    subparsers.add_parser("check_positions", help="Check for position changes")

    # Odds Movement
    subparsers.add_parser("check_odds", help="Check for odds movement")

    # Smart Money
    subparsers.add_parser("smart-money", help="Identify smart money wallets")

    # Profile wallet (vet + print metrics for tuning config)
    prof_p = subparsers.add_parser(
        "profile",
        help="Vet a wallet and print metrics for tuning config (use with known-good wallet)",
    )
    prof_p.add_argument("address", help="Wallet address (0x...)")

    return parser


def _configure_logging():
    """Stderr logging for library code (dashboard, API client, etc.)."""
    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not logging.root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def main():
    """Main CLI entry point."""
    _configure_logging()
    parser = setup_argument_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print("\nExamples:")

    # Initialize core components
    config = Config(args.config)
    storage = WalletStorage(db_path=DB_PATH)
    api_factory = APIClientFactory(config)

    # Command mapping
    command_map = {
        "add": add_wallet,
        "remove": remove_wallet,
        "list": list_wallets,
        "refresh": handle_refresh_command,
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
        "run": handle_run_command,
        "check_positions": handle_check_positions_command,
        "check_odds": handle_check_odds_command,
        "smart-money": handle_smart_money_command,
        "profile": handle_profile_command,
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
        "run": [storage, config, api_factory],
        "check_positions": [storage, config, api_factory],
        "check_odds": [storage, config, api_factory],
        "smart-money": [storage, config, api_factory],
        "profile": [storage, config, api_factory],
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


if __name__ == "__main__":
    main()
