"""Telegram bot for interacting with PolySuite."""

import telebot
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.utils import is_valid_address
from src.agent import Agent
from src.config import Config, get_bankr_client
from src.market.api import APIClientFactory
from src.market.bankr import BankrClient


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
        # Use shared Bankr client
        self.bankr = get_bankr_client(config.bankr_api_key if config else "")
        self.agent = Agent(config=config, storage=storage, api_factory=api_factory)
        self.user_timestamps = {}
        self.user_bankr_keys = {}  # user_id -> Bankr API key
        self.rate_limit_seconds = 5  # 5 seconds between commands

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
                self.storage.add_wallet(Wallet(address=address, nickname=address[:12] + "..."))
                self.bot.reply_to(message, f"Added wallet: {address}")
            except IndexError:
                self.bot.reply_to(message, "Usage: /add <address>")

        @self.bot.message_handler(commands=["connectbankr"])
        @rate_limited
        def connect_bankr(message):
            """Connect user's own Bankr API key."""
            try:
                api_key = message.text.split()[1].strip()
                if not api_key.startswith("bk_"):
                    self.bot.reply_to(
                        message, "Invalid Bankr API key format. Should start with 'bk_'"
                    )
                    return

                # Validate the key works
                test_client = BankrClient(api_key=api_key)
                if not test_client.is_configured():
                    self.bot.reply_to(message, "Invalid API key.")
                    return

                # Store the user's key
                user_id = message.from_user.id
                self.user_bankr_keys[user_id] = api_key

                self.bot.reply_to(
                    message,
                    "Bankr connected! Your API key is now linked to your account. Use /ask for prices, balances, etc.",
                )
            except IndexError:
                self.bot.reply_to(
                    message,
                    "Usage: /connectbankr <your_bankr_api_key>\n\nGet your key at: https://bankr.bot/api",
                )

        @self.bot.message_handler(commands=["bankrstatus"])
        @rate_limited
        def bankr_status(message):
            """Check Bankr connection status."""
            user_id = message.from_user.id
            if user_id in self.user_bankr_keys:
                self.bot.reply_to(
                    message, "Bankr: Connected ✅\nYour own API key is in use."
                )
            elif self.bankr and self.bankr.is_configured():
                self.bot.reply_to(
                    message,
                    "Bankr: Using default key\nConnect your own with /connectbankr <key>",
                )
            else:
                self.bot.reply_to(
                    message, "Bankr: Not connected\nConnect with /connectbankr <key>"
                )

        @self.bot.message_handler(commands=["ai", "bankr"])
        @rate_limited
        def ai_bankr(message):
            """AI/Bankr command - ask anything via Bankr."""
            try:
                user_input = message.text
                # Remove both /ai and /bankr prefixes
                for prefix in ["/ai", "/bankr"]:
                    user_input = user_input.replace(prefix, "").strip()

                if not user_input:
                    self.bot.reply_to(
                        message,
                        "Usage: /ai <your question>\nExample: /ai what's the price of SOL?",
                    )
                    return

                self.bot.reply_to(message, "Thinking...")

                # Check if user has their own Bankr key
                user_id = message.from_user.id
                if user_id in self.user_bankr_keys:
                    from src.agent import Agent

                    user_agent = Agent(
                        config=self.agent.config,
                        storage=self.agent.storage,
                        api_factory=self.agent.api_factory,
                    )
                    user_agent.bankr = BankrClient(
                        api_key=self.agent.config.bankr_api_key
                        if self.agent.config
                        else "",
                        user_api_key=self.user_bankr_keys[user_id],
                    )
                    response = user_agent.chat(user_input)
                else:
                    response = self.agent.chat(user_input)

                self.bot.reply_to(message, response)
            except Exception as e:
                self.bot.reply_to(message, f"Error: {str(e)[:200]}")

        @self.bot.message_handler(commands=["ask"])
        @rate_limited
        def ask(message):
            user_input = message.text.replace("/ask", "").strip()
            if not user_input:
                self.bot.reply_to(message, "Usage: /ask <your question>")
                return

            self.bot.reply_to(message, "Thinking...")

            # Check if user has their own Bankr key
            user_id = message.from_user.id
            if user_id in self.user_bankr_keys:
                # Use user's own Bankr key
                from src.agent import Agent

                user_agent = Agent(
                    config=self.agent.config,
                    storage=self.agent.storage,
                    api_factory=self.agent.api_factory,
                )
                user_agent.bankr = BankrClient(
                    api_key=self.agent.config.bankr_api_key
                    if self.agent.config
                    else "",
                    user_api_key=self.user_bankr_keys[user_id],
                )
                response = user_agent.chat(user_input)
            else:
                response = self.agent.chat(user_input)

            self.bot.reply_to(message, response)

    def run(self):
        """Run the bot."""
        self.bot.polling()
