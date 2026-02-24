#!/usr/bin/env python3
"""Prediction Suite - Startup Script

Usage:
    python start.py              # Run main bot only
    python start.py --monitor    # Run with market monitor
    python start.py --discord    # Run with Discord bot
    python start.py --telegram  # Run with Telegram bot
    python start.py --all       # Run everything
"""

import sys
import os
import argparse

# Load environment
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Prediction Suite")
    parser.add_argument("--monitor", action="store_true", help="Run market monitor")
    parser.add_argument("--discord", action="store_true", help="Run Discord bot")
    parser.add_argument("--telegram", action="store_true", help="Run Telegram bot")
    parser.add_argument("--all", action="store_true", help="Run all")
    args = parser.parse_args()

    # Default: run main bot
    run_monitor = args.monitor or args.all
    run_discord = args.discord or args.all
    run_telegram = args.telegram or args.all

    # If no args, run main only
    if not (run_monitor or run_discord or run_telegram):
        run_monitor = True

    print("=" * 50)
    print("  Prediction Suite")
    print("=" * 50)

    if run_monitor:
        print("[*] Starting market monitor...")
        import main as bot_main

        bot_main.main()

    if run_discord:
        print("[*] Starting Discord bot...")
        from src.discord_bot import DiscordBot
        from src.wallet.storage import WalletStorage
        from src.config import Config

        storage = WalletStorage()
        config = Config()
        discord = DiscordBot(
            token=config.discord_bot_token, storage=storage, config=config
        )
        discord.run()

    if run_telegram:
        print("[*] Starting Telegram bot...")
        from src.telegram_bot import TelegramBot
        from src.wallet.storage import WalletStorage
        from src.config import Config

        storage = WalletStorage()
        config = Config()
        telegram = TelegramBot(
            token=config.telegram_bot_token, storage=storage, config=config
        )
        telegram.run()


if __name__ == "__main__":
    main()
