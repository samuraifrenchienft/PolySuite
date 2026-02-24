"""Telegram bot for Prediction Suite."""

import telebot
import os
import requests
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.utils import is_valid_address
from src.agent import Agent
from src.config import Config
from src.market.api import APIClientFactory


import time


class TelegramBot:
    """Telegram bot for interacting with PolySuite."""

    def __init__(
        self,
        token: str,
        storage: WalletStorage,
        config: Config = None,
        api_factory: APIClientFactory = None,
    ):
        """Initialize the bot."""
        self.bot = telebot.TeleBot(token)
        self.storage = storage
        self.config = config
        self.agent = Agent(config=config, storage=storage, api_factory=api_factory)
        self.user_timestamps = {}

        # Groq AI (primary)
        self.groq_key = os.getenv("Groq_api_key") or os.getenv("GROQ_API_KEY")
        # OpenRouter (backup)
        self.openrouter_key = os.getenv("Openrouter_api_key") or os.getenv(
            "OPENROUTER_API_KEY"
        )

        def rate_limited(handler):
            def wrapper(message):
                user_id = message.from_user.id
                current_time = time.time()

                if user_id in self.user_timestamps:
                    last_call = self.user_timestamps[user_id]
                    if current_time - last_call < self.rate_limit_seconds:
                        self.bot.reply_to(
                            message,
                            "You are sending commands too quickly. Please wait a moment.",
                        )
                        return

                self.user_timestamps[user_id] = current_time
                return handler(message)

            return wrapper

        @self.bot.message_handler(commands=["start"])
        @rate_limited
        def start(message):
            self.bot.reply_to(message, "Welcome to PolySuite!")

        @self.bot.message_handler(commands=["status"])
        @rate_limited
        def status(message):
            wallets = self.storage.list_wallets()
            self.bot.reply_to(message, f"Tracking {len(wallets)} wallets.")

        @self.bot.message_handler(commands=["add"])
        @rate_limited
        def add(message):
            try:
                address = message.text.split()[1]
                if not is_valid_address(address):
                    self.bot.reply_to(message, "Invalid wallet address format.")
                    return
                self.storage.add_wallet(
                    Wallet(address=address, nickname=address[:12] + "...")
                )
                self.bot.reply_to(message, f"Added wallet: {address}")
            except IndexError:
                self.bot.reply_to(message, "Usage: /add <address>")

        @self.bot.message_handler(commands=["ai", "ask"])
        def ask_ai(message):
            """AI command - no rate limit, Groq handles long questions."""
            try:
                user_input = message.text
                for prefix in ["/ai", "/ask"]:
                    user_input = user_input.replace(prefix, "").strip()

                if not user_input:
                    self.bot.reply_to(message, "Usage: /ai <your question>")
                    return

                self.bot.reply_to(message, "🤔 Thinking...")

                # Use Groq AI
                response = self._call_ai(user_input)
                self.bot.reply_to(message, f"🤖 {response[:2000]}")

            except Exception as e:
                self.bot.reply_to(message, f"Error: {str(e)[:200]}")

    def run(self):
        """Run the bot."""
        self.bot.polling()
