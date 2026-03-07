"""Telegram bot for Prediction Suite."""

import telebot
import json
import os
from pathlib import Path
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
        # Connect flow: user_id -> {waiting: "polymarket"|"kalshi", since: float}
        self._connect_pending: dict = {}
        # Menu flow: user_id -> {action: str, since: float, chat_id: int}
        self._menu_pending: dict = {}
        self._connect_timeout = 300  # 5 min

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

        def _format_vetted_rankings(mode: str, limit: int = 5) -> str:
            limit = max(1, min(int(limit or 5), 20))
            vetting_path = Path("data/vetted_leaderboard.json")
            if not vetting_path.exists():
                return "No vetted leaderboard yet. Run monitor/background vetting first."
            try:
                with open(vetting_path) as f:
                    wallets = (json.load(f) or {}).get("wallets", []) or []
            except Exception:
                return "Failed to read vetted leaderboard."
            if not wallets:
                return "No vetted wallets available."

            if mode == "streak":
                wallets.sort(
                    key=lambda w: (
                        float(w.get("current_win_streak", 0) or 0),
                        float(w.get("recent_win_rate", 0) or 0),
                        float(w.get("reliability_score", 0) or 0),
                    ),
                    reverse=True,
                )
                header = "Top streak wallets"
            else:
                wallets.sort(
                    key=lambda w: (
                        float(w.get("reliability_score", 0) or 0),
                        float(w.get("recent_win_rate", 0) or 0),
                        float(w.get("current_win_streak", 0) or 0),
                    ),
                    reverse=True,
                )
                header = "Top reliable wallets"

            lines = [f"{header}:"]
            for i, w in enumerate(wallets[:limit], 1):
                name = w.get("nickname") or (w.get("address", "")[:10] + "...")
                rel = float(w.get("reliability_score", 0) or 0)
                streak = int(w.get("current_win_streak", 0) or 0)
                recent = float(w.get("recent_win_rate", 0) or 0)
                lines.append(
                    f"{i}. {name} | Rel {rel:.1f} | Streak {streak} | Recent {recent:.1f}%"
                )
            return "\n".join(lines)

        @self.bot.message_handler(commands=["start"])
        @rate_limited
        def start(message):
            self.bot.reply_to(
                message,
                (
                    "Welcome to PolySuite!\n\n"
                    "Quick links:\n"
                    "• /menu\n"
                    "• /status\n"
                    "• /top_reliable_wallets\n"
                    "• /top_streak_wallets\n"
                    "• /copy status"
                ),
            )

        @self.bot.message_handler(commands=["menu"])
        @rate_limited
        def menu(message):
            """Show menu with inline buttons."""
            kb = telebot.types.InlineKeyboardMarkup()
            kb.row(
                telebot.types.InlineKeyboardButton("Status", callback_data="m:status"),
                telebot.types.InlineKeyboardButton("Copy status", callback_data="m:copy_status"),
            )
            kb.row(
                telebot.types.InlineKeyboardButton("Add wallet", callback_data="m:add"),
                telebot.types.InlineKeyboardButton("Remove wallet", callback_data="m:remove"),
            )
            kb.row(
                telebot.types.InlineKeyboardButton("Copy add", callback_data="m:copy_add"),
                telebot.types.InlineKeyboardButton("Copy remove", callback_data="m:copy_remove"),
                telebot.types.InlineKeyboardButton("Copy list", callback_data="m:copy_list"),
            )
            kb.row(
                telebot.types.InlineKeyboardButton("Connect Polymarket", callback_data="m:conn_pm"),
                telebot.types.InlineKeyboardButton("Connect Kalshi", callback_data="m:conn_k"),
            )
            kb.row(
                telebot.types.InlineKeyboardButton("Copy kill", callback_data="m:copy_kill"),
                telebot.types.InlineKeyboardButton("Copy settings", callback_data="m:copy_settings"),
            )
            kb.row(
                telebot.types.InlineKeyboardButton("Top reliable", callback_data="m:top_reliable"),
                telebot.types.InlineKeyboardButton("Top streak", callback_data="m:top_streak"),
            )
            kb.row(telebot.types.InlineKeyboardButton("Ask AI", callback_data="m:ai"))
            self.bot.reply_to(message, "Choose an action:", reply_markup=kb)

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("m:"))
        def menu_callback(callback):
            """Handle menu button clicks."""
            self.bot.answer_callback_query(callback.id)
            uid = callback.from_user.id
            chat_id = callback.message.chat.id
            action = (callback.data or "").replace("m:", "")
            if action == "status":
                wallets = self.storage.list_wallets()
                self.bot.send_message(chat_id, f"Tracking {len(wallets)} wallets.")
            elif action == "copy_status":
                try:
                    from src.copy import list_copy_targets
                    targets = list_copy_targets()
                    enabled = (self.config or {}).get("copy_enabled", False)
                    dry_run = (self.config or {}).get("copy_dry_run", True)
                    msg = f"Copy: {'ON' if enabled else 'OFF'} | Dry run: {'Yes' if dry_run else 'No'}\nTargets: {len(targets)}"
                    self.bot.send_message(chat_id, msg[:2000])
                except Exception:
                    self.bot.send_message(chat_id, "Copy status failed.")
            elif action == "copy_list":
                try:
                    from src.copy import list_copy_targets
                    targets = list_copy_targets()
                    if not targets:
                        self.bot.send_message(chat_id, "No copy targets.")
                    else:
                        msg = f"Copy targets ({len(targets)}):\n" + "\n".join(f"• {t.get('nickname', t.get('address','')[:10])}" for t in targets[:15])
                        self.bot.send_message(chat_id, msg[:2000])
                except Exception:
                    self.bot.send_message(chat_id, "Copy list failed.")
            elif action == "copy_kill":
                try:
                    if self.config and hasattr(self.config, "set"):
                        self.config.set("copy_pause", True)
                        if hasattr(self.config, "save"):
                            self.config.save()
                        self.bot.send_message(chat_id, "Copy PAUSED (kill switch). Use /copy resume to re-enable.")
                    else:
                        self.bot.send_message(chat_id, "Config not available.")
                except Exception:
                    self.bot.send_message(chat_id, "Failed.")
            elif action == "copy_settings":
                try:
                    cfg = self.config.config if (self.config and hasattr(self.config, "config")) else (self.config or {})
                    msg = "Copy settings:\n"
                    msg += f"Max order: ${cfg.get('copy_max_order_usd', 100)}\n"
                    msg += f"Size mult: {cfg.get('copy_size_multiplier', 1.0)}\n"
                    msg += f"Throttle: {cfg.get('copy_max_trades_per_minute', 0) or 'off'}/min\n"
                    msg += f"Risk reduction: after {cfg.get('copy_reduce_multiplier_after_trades', 0) or 0} trades -> {cfg.get('copy_reduced_multiplier', 0.5)}x\n"
                    msg += f"Freeze: after {cfg.get('copy_freeze_after_trades', 0) or 0} trades for {cfg.get('copy_freeze_duration_minutes', 60)} min\n"
                    msg += f"Fee: {cfg.get('copy_fee_pct', 0.77)}% | Referral: {cfg.get('copy_referral_discount_pct', 10)}%\n"
                    msg += f"Paused: {cfg.get('copy_pause', False)}"
                    self.bot.send_message(chat_id, msg[:2000])
                except Exception:
                    self.bot.send_message(chat_id, "Failed.")
            elif action == "top_reliable":
                self.bot.send_message(chat_id, _format_vetted_rankings("reliable", 5)[:4000])
            elif action == "top_streak":
                self.bot.send_message(chat_id, _format_vetted_rankings("streak", 5)[:4000])
            elif action == "conn_pm":
                if getattr(callback.message.chat, "type", "") != "private":
                    self.bot.send_message(chat_id, "Use /connect polymarket in a DM for security.")
                else:
                    self._connect_pending[uid] = {"waiting": "polymarket", "since": time.time()}
                    self.bot.send_message(chat_id, "Paste: api_key|api_secret|api_passphrase")
            elif action == "conn_k":
                if getattr(callback.message.chat, "type", "") != "private":
                    self.bot.send_message(chat_id, "Use /connect kalshi in a DM for security.")
                else:
                    self._connect_pending[uid] = {"waiting": "kalshi", "since": time.time()}
                    self.bot.send_message(chat_id, "Paste: api_key_id|private_key_pem")
            elif action == "ai":
                self.bot.send_message(chat_id, "Use /ai <your question> to ask.")
            elif action in ("add", "remove", "copy_add", "copy_remove"):
                self._menu_pending[uid] = {"action": action, "since": time.time(), "chat_id": chat_id}
                prompts = {"add": "Send wallet address [nickname]", "remove": "Send wallet address to remove", "copy_add": "Send: address [nickname]", "copy_remove": "Send wallet address to remove from copy"}
                self.bot.send_message(chat_id, prompts.get(action, "Send your input."))

        @self.bot.message_handler(commands=["status"])
        @rate_limited
        def status(message):
            wallets = self.storage.list_wallets()
            self.bot.reply_to(message, f"Tracking {len(wallets)} wallets.")

        @self.bot.message_handler(commands=["top_reliable_wallets"])
        @rate_limited
        def top_reliable_wallets(message):
            try:
                parts = (message.text or "").split()
                limit = int(parts[1]) if len(parts) > 1 else 5
            except Exception:
                limit = 5
            self.bot.reply_to(message, _format_vetted_rankings("reliable", limit)[:4000])

        @self.bot.message_handler(commands=["top_streak_wallets"])
        @rate_limited
        def top_streak_wallets(message):
            try:
                parts = (message.text or "").split()
                limit = int(parts[1]) if len(parts) > 1 else 5
            except Exception:
                limit = 5
            self.bot.reply_to(message, _format_vetted_rankings("streak", limit)[:4000])

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

        @self.bot.message_handler(commands=["copy"])
        @rate_limited
        def copy_cmd(message):
            """Copy trading: /copy add <addr> [nick], /copy remove <addr>, /copy list, /copy status"""
            try:
                from src.copy import add_copy_target, remove_copy_target, list_copy_targets
                parts = message.text.split(maxsplit=2)
                sub = (parts[1].lower() if len(parts) > 1 else "").strip()
                rest = (parts[2] if len(parts) > 2 else "").strip()

                if sub == "add":
                    add_parts = rest.split(maxsplit=1)
                    addr = add_parts[0] if add_parts else ""
                    nick = add_parts[1] if len(add_parts) > 1 else ""
                    if not addr or not is_valid_eth_address(addr):
                        self.bot.reply_to(message, "Usage: /copy add <address> [nickname]")
                        return
                    ok = add_copy_target(addr, nick)
                    if ok:
                        targets = list_copy_targets()
                        self.bot.reply_to(message, f"Added {addr[:12]}... to copy targets ({len(targets)} total).")
                    else:
                        if any(t.get("address", "").lower() == addr.lower() for t in list_copy_targets()):
                            self.bot.reply_to(message, "Already in copy targets.")
                        else:
                            self.bot.reply_to(message, "Limit reached (20 targets). Remove one first.")
                    return

                if sub == "remove":
                    addr = rest.split()[0] if rest else ""
                    if not addr or not is_valid_eth_address(addr):
                        self.bot.reply_to(message, "Usage: /copy remove <address>")
                        return
                    ok = remove_copy_target(addr)
                    if ok:
                        targets = list_copy_targets()
                        self.bot.reply_to(message, f"Removed {addr[:12]}... ({len(targets)} targets left).")
                    else:
                        self.bot.reply_to(message, "Not in copy targets.")
                    return

                if sub == "list":
                    targets = list_copy_targets()
                    if not targets:
                        self.bot.reply_to(message, "No copy targets. Use /copy add <address> to add.")
                        return
                    msg = f"Copy targets ({len(targets)}):\n\n"
                    for t in targets[:15]:
                        addr = t.get("address", "?")[:10] + "..."
                        nick = t.get("nickname", "")
                        msg += f"• {nick or addr} ({addr})\n"
                    if len(targets) > 15:
                        msg += f"\n... and {len(targets) - 15} more"
                    self.bot.reply_to(message, msg[:2000])
                    return

                if sub == "kill":
                    try:
                        if self.config and hasattr(self.config, "set"):
                            self.config.set("copy_pause", True)
                            if hasattr(self.config, "save"):
                                self.config.save()
                            self.bot.reply_to(message, "Copy trading PAUSED (kill switch). Use /copy resume to re-enable.")
                        else:
                            self.bot.reply_to(message, "Config not available for kill switch.")
                    except Exception:
                        self.bot.reply_to(message, "Failed to save config.")
                    return

                if sub == "resume":
                    try:
                        if self.config and hasattr(self.config, "set"):
                            self.config.set("copy_pause", False)
                            if hasattr(self.config, "save"):
                                self.config.save()
                            self.bot.reply_to(message, "Copy trading resumed.")
                        else:
                            self.bot.reply_to(message, "Config not available.")
                    except Exception:
                        self.bot.reply_to(message, "Failed to save config.")
                    return

                if sub == "settings":
                    try:
                        cfg = self.config.config if hasattr(self.config, "config") else (self.config or {})
                        msg = "Copy settings:\n"
                        msg += f"Max order: ${cfg.get('copy_max_order_usd', 100)}\n"
                        msg += f"Size mult: {cfg.get('copy_size_multiplier', 1.0)}\n"
                        msg += f"Throttle: {cfg.get('copy_max_trades_per_minute', 0) or 'off'}/min\n"
                        msg += f"Risk reduction: after {cfg.get('copy_reduce_multiplier_after_trades', 0) or 0} trades -> {cfg.get('copy_reduced_multiplier', 0.5)}x\n"
                        msg += f"Freeze: after {cfg.get('copy_freeze_after_trades', 0) or 0} trades for {cfg.get('copy_freeze_duration_minutes', 60)} min\n"
                        msg += f"Fee: {cfg.get('copy_fee_pct', 0.77)}% | Referral: {cfg.get('copy_referral_discount_pct', 10)}%\n"
                        msg += f"Paused: {cfg.get('copy_pause', False)}"
                        self.bot.reply_to(message, msg[:2000])
                    except Exception:
                        self.bot.reply_to(message, "Failed.")
                    return

                if sub in ("status", ""):
                    targets = list_copy_targets()
                    enabled = (self.config or {}).get("copy_enabled", False)
                    dry_run = (self.config or {}).get("copy_dry_run", True)
                    msg = f"Copy: {'ON' if enabled else 'OFF'} | Dry run: {'Yes' if dry_run else 'No'}\n"
                    msg += f"Targets: {len(targets)}"
                    if targets:
                        msg += "\nTop: " + ", ".join((t.get("nickname") or t.get("address", "")[:10]) for t in targets[:5])
                    self.bot.reply_to(message, msg[:2000])
                    return

                self.bot.reply_to(message, "Usage: /copy add|remove|list|status|kill|resume|settings")
            except Exception as e:
                print(f"[Telegram/copy] Error: {e}")
                self.bot.reply_to(message, "Copy command failed. Try /copy list or /copy status.")

        @self.bot.message_handler(commands=["copystatus"])
        @rate_limited
        def copystatus(message):
            try:
                from src.copy import list_copy_targets
                targets = list_copy_targets()
                enabled = (self.config or {}).get("copy_enabled", False)
                dry_run = (self.config or {}).get("copy_dry_run", True)
                msg = f"Copy: {'ON' if enabled else 'OFF'} | Dry run: {'Yes' if dry_run else 'No'}\n"
                msg += f"Targets: {len(targets)}"
                if targets:
                    msg += "\nTop: " + ", ".join((t.get("nickname") or t.get("address", "")[:10]) for t in targets[:5])
                self.bot.reply_to(message, msg[:2000])
            except Exception as e:
                print(f"[Telegram/copystatus] Error: {e}")
                self.bot.reply_to(message, "Failed.")

        @self.bot.message_handler(commands=["connect"])
        @rate_limited
        def connect_cmd(message):
            """Connect Polymarket or Kalshi: /connect polymarket, /connect kalshi. DM only."""
            chat_type = message.chat.type if hasattr(message.chat, "type") else "private"
            if chat_type != "private":
                self.bot.reply_to(message, "For security, use /connect polymarket or /connect kalshi in a DM with me.")
                return
            parts = (message.text or "").split(maxsplit=1)
            platform = (parts[1].lower().strip() if len(parts) > 1 else "")
            if platform == "polymarket":
                self._connect_pending[message.from_user.id] = {"waiting": "polymarket", "since": time.time()}
                self.bot.reply_to(message, "Paste your Polymarket API credentials in one message:\napi_key|api_secret|api_passphrase\n(Separated by |, from polymarket.com/settings)")
            elif platform == "kalshi":
                self._connect_pending[message.from_user.id] = {"waiting": "kalshi", "since": time.time()}
                self.bot.reply_to(message, "Paste your Kalshi API credentials in one message:\napi_key_id|private_key_pem\n(Private key: full PEM block. Use \\n for newlines if needed.)")
            else:
                self.bot.reply_to(message, "Usage: /connect polymarket or /connect kalshi (DM only)")

        def _handle_menu_paste(message):
            """Handle add/remove/copy input when user is in menu pending state."""
            uid = message.from_user.id
            if uid not in self._menu_pending:
                return False
            entry = self._menu_pending[uid]
            if time.time() - entry["since"] > self._connect_timeout:
                del self._menu_pending[uid]
                return False
            text = (message.text or "").strip()
            if not text or text.startswith("/"):
                return False
            action = entry["action"]
            chat_id = entry.get("chat_id", message.chat.id)
            del self._menu_pending[uid]
            try:
                if action == "add":
                    parts = text.split(maxsplit=1)
                    addr = parts[0]
                    nick = parts[1] if len(parts) > 1 else addr[:12] + "..."
                    if not is_valid_eth_address(addr):
                        self.bot.send_message(chat_id, "Invalid address.")
                        return True
                    if self.storage.get_wallet(addr):
                        self.bot.send_message(chat_id, "Already tracking.")
                        return True
                    if len(self.storage.list_wallets()) >= MAX_WALLETS:
                        self.bot.send_message(chat_id, f"Limit ({MAX_WALLETS}) reached.")
                        return True
                    self.storage.add_wallet(Wallet(address=addr, nickname=sanitize_nickname(nick) or nick))
                    self.bot.send_message(chat_id, f"Added {nick}.")
                elif action == "remove":
                    if not is_valid_eth_address(text):
                        self.bot.send_message(chat_id, "Invalid address.")
                        return True
                    ok = self.storage.remove_wallet(text)
                    self.bot.send_message(chat_id, f"Removed {text[:12]}..." if ok else "Not found.")
                elif action == "copy_add":
                    from src.copy import add_copy_target, list_copy_targets
                    parts = text.split(maxsplit=1)
                    addr = parts[0]
                    nick = parts[1] if len(parts) > 1 else ""
                    if not is_valid_eth_address(addr):
                        self.bot.send_message(chat_id, "Invalid address.")
                        return True
                    ok = add_copy_target(addr, nick)
                    targets = list_copy_targets()
                    self.bot.send_message(chat_id, f"Added ({len(targets)} targets)." if ok else "Already in list or limit reached.")
                elif action == "copy_remove":
                    from src.copy import remove_copy_target, list_copy_targets
                    if not is_valid_eth_address(text):
                        self.bot.send_message(chat_id, "Invalid address.")
                        return True
                    ok = remove_copy_target(text)
                    targets = list_copy_targets()
                    self.bot.send_message(chat_id, f"Removed ({len(targets)} left)." if ok else "Not in list.")
                return True
            except Exception as e:
                print(f"[Telegram/menu] Error: {e}")
                self.bot.send_message(chat_id, "Failed.")
                return True

        def _handle_connect_paste(message):
            """Handle credential paste when user is in connect pending state."""
            uid = message.from_user.id
            if uid not in self._connect_pending:
                return False
            entry = self._connect_pending[uid]
            if time.time() - entry["since"] > self._connect_timeout:
                del self._connect_pending[uid]
                return False
            platform = entry["waiting"]
            text = (message.text or "").strip()
            if not text or text.startswith("/"):
                return False
            del self._connect_pending[uid]
            try:
                from src.auth.credential_store import store_credentials
                user_id = str(uid)
                if platform == "polymarket":
                    parts = text.split("|", 2)
                    if len(parts) < 3:
                        self.bot.reply_to(message, "Format: api_key|api_secret|api_passphrase")
                        return True
                    store_credentials(user_id, "polymarket", {"api_key": parts[0].strip(), "api_secret": parts[1].strip(), "api_passphrase": parts[2].strip()})
                    self.bot.reply_to(message, "Polymarket credentials saved.")
                elif platform == "kalshi":
                    parts = text.split("|", 1)
                    if len(parts) < 2:
                        self.bot.reply_to(message, "Format: api_key_id|private_key_pem")
                        return True
                    pem = parts[1].strip().replace("\\n", "\n")
                    store_credentials(user_id, "kalshi", {"api_key_id": parts[0].strip(), "private_key_pem": pem})
                    self.bot.reply_to(message, "Kalshi credentials saved.")
                return True
            except RuntimeError:
                self.bot.reply_to(message, "Credential storage not configured.")
                return True
            except Exception as e:
                print(f"[Telegram/connect] Error: {e}")
                self.bot.reply_to(message, "Failed to save. Check format and try again.")
                return True

        @self.bot.message_handler(func=lambda m: (m.text or "").strip() and not (m.text or "").strip().startswith("/"))
        def paste_handler(message):
            """Handle menu or connect paste (add/remove/copy/creds)."""
            if _handle_menu_paste(message):
                return
            _handle_connect_paste(message)

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
