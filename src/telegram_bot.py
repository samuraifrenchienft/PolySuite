"""Telegram bot for Prediction Suite."""

import telebot
import os
import requests
import time
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.utils import is_valid_eth_address, sanitize_nickname
from src.agent import Agent
from src.config import Config
from src.market.api import APIClientFactory

MAX_WALLETS = 10


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
        self.token = token
        self.bot = telebot.TeleBot(token)
        self.storage = storage
        self.config = config
        self.agent = Agent(config=config, storage=storage, api_factory=api_factory)
        self.user_timestamps = {}
        self.rate_limit_seconds = 10

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
                parts = message.text.split()
                if len(parts) < 2:
                    self.bot.reply_to(message, "Usage: /add <address> [nickname]")
                    return

                address = parts[1]
                if not is_valid_eth_address(address):
                    self.bot.reply_to(message, "Invalid wallet address format.")
                    return

                wallets = self.storage.list_wallets()
                if self.storage.get_wallet(address):
                    self.bot.reply_to(message, "Already tracking this wallet.")
                    return
                if len(wallets) >= MAX_WALLETS:
                    self.bot.reply_to(
                        message,
                        f"Limit reached ({MAX_WALLETS} wallets). Remove one first.",
                    )
                    return

                raw_nick = parts[2] if len(parts) > 2 else address[:12] + "..."
                nickname = sanitize_nickname(raw_nick) or address[:12] + "..."

                self.storage.add_wallet(Wallet(address=address, nickname=nickname))
                self.bot.reply_to(
                    message,
                    f"Added {nickname}.\nTracking {len(wallets) + 1}/{MAX_WALLETS} wallets.",
                )
            except IndexError:
                self.bot.reply_to(message, "Usage: /add <address> [nickname]")

        @self.bot.message_handler(commands=["remove"])
        @rate_limited
        def remove(message):
            try:
                parts = message.text.split()
                if len(parts) < 2:
                    self.bot.reply_to(message, "Usage: /remove <address>")
                    return
                address = parts[1]
                removed = self.storage.remove_wallet(address)
                if removed:
                    self.bot.reply_to(message, f"Removed {address[:12]}...")
                else:
                    self.bot.reply_to(message, "Wallet not found.")
            except Exception:
                self.bot.reply_to(message, "Usage: /remove <address>")

        @self.bot.message_handler(commands=["ai", "ask"])
        def ask_ai(message):
            """AI command - uses Agent (Bankr for crypto, chat for general)."""
            try:
                user_input = message.text
                for prefix in ["/ai", "/ask"]:
                    user_input = user_input.replace(prefix, "").strip()

                if not user_input:
                    self.bot.reply_to(message, "Usage: /ai <your question>")
                    return

                self.bot.reply_to(message, "🤔 Thinking...")
                response = self._call_ai(user_input)
                self.bot.reply_to(message, f"🤖 {response[:2000]}")

            except Exception as e:
                print(f"[Telegram/AI] Error: {e}")
                self.bot.reply_to(message, "AI temporarily unavailable. Please try again.")

    def _call_ai(self, message: str) -> str:
        """Route to Agent for market/crypto queries or general chat."""
        return self.agent.chat(message)

    def _set_menu_button(self):
        """Set Web App menu button if DASHBOARD_URL is configured."""
        url = os.getenv("DASHBOARD_URL", "").strip()
        if not url:
            return
        try:
            payload = {
                "menu_button": {
                    "type": "web_app",
                    "text": "📊 Dashboard",
                    "web_app": {"url": url},
                }
            }
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/setChatMenuButton",
                json=payload,
                timeout=10,
            )
            if r.ok:
                print("[*] Telegram menu button set (Dashboard)")
            else:
                print(f"[!] Menu button failed: {r.text[:100]}")
        except Exception as e:
            print(f"[!] Menu button error: {e}")

    def run(self):
        """Run the bot."""
        self._set_menu_button()
        self.bot.polling()
