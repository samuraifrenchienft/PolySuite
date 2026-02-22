"""Discord bot for PolySuite - hybrid approach with both slash and message commands."""

import discord
from discord import app_commands
from discord.ext import commands
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.utils import is_valid_address
from src.agent import Agent
from src.config import Config, get_bankr_client
import asyncio
import os
import requests


class DiscordBot(commands.Bot):
    """Discord bot for PolySuite."""

    def __init__(
        self,
        token: str,
        storage: WalletStorage,
        config: Config = None,
        api_factory=None,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        app_id = config.discord_application_id if config else None
        super().__init__(command_prefix="!", intents=intents, application_id=app_id)

        self.token = token
        self.storage = storage
        self.config = config
        self.api_factory = api_factory
        self.bankr = get_bankr_client(config.bankr_api_key if config else "")
        self.agent = Agent(config=config, storage=storage, api_factory=api_factory)

        # === SLASH COMMANDS ===
        @self.tree.command(
            name="bankr",
            description="Ask Bankr AI (crypto, markets, balances). Max 100 chars; use !bankr for longer.",
        )
        async def bankr_slash(interaction: discord.Interaction, question: str):
            await self._handle_ai(interaction, question.strip(), "bankr")

        @self.tree.command(
            name="ask",
            description="Ask AI anything. Max 100 chars; use !ask for longer prompts.",
        )
        async def ask_slash(interaction: discord.Interaction, question: str):
            await self._handle_ai(interaction, question.strip(), "ask")

        @self.tree.command(
            name="deploy", description="Deploy a token on Base via Bankr"
        )
        async def deploy_slash(
            interaction: discord.Interaction,
            name: str,
            symbol: str = None,
            description: str = None,
            fee_recipient: str = None,
            simulate: bool = False,
        ):
            """Deploy a token on Base blockchain via Bankr."""
            if not self.bankr or not self.bankr.is_configured():
                await interaction.response.send_message(
                    "Bankr not configured. Add BANKR_API_KEY to .env", ephemeral=True
                )
                return

            await interaction.response.send_message(
                f"Deploying token '{name}' on Base...", ephemeral=True
            )

            try:
                result = self.bankr.deploy_token(
                    token_name=name,
                    token_symbol=symbol,
                    description=description,
                    fee_recipient=fee_recipient,
                    simulate_only=simulate,
                )

                if result and not result.get("error"):
                    token_addr = result.get("tokenAddress", "Unknown")
                    pool_id = result.get("poolId", "Unknown")
                    chain = result.get("chain", "base")

                    msg = f"✅ **Token Deployed!**\n\n"
                    msg += f"**Name:** {name}\n"
                    if symbol:
                        msg += f"**Symbol:** {symbol}\n"
                    msg += f"**Chain:** {chain}\n"
                    msg += f"**Token:** `{token_addr}`\n"
                    msg += f"**Pool:** `{pool_id}`"

                    if result.get("simulated"):
                        msg += "\n\n_(This was a simulation)_"

                    await interaction.followup.send(msg)
                else:
                    err = (
                        result.get("error", "Unknown error")
                        if result
                        else "Failed to deploy"
                    )
                    await interaction.followup.send(f"❌ Deploy failed: {err}")

            except Exception as e:
                await interaction.followup.send(f"❌ Error: {str(e)[:200]}")

        @self.tree.command(name="status", description="Check wallets")
        async def status_slash(interaction: discord.Interaction):
            wallets = self.storage.list_wallets()
            smart_money = [w for w in wallets if w.is_smart_money]
            msg = f"Tracking {len(wallets)} wallets ({len(smart_money)} smart)"
            if wallets:
                msg += "\n\nTop:"
                for w in sorted(wallets, key=lambda x: x.win_rate, reverse=True)[:5]:
                    msg += f"\n• {w.nickname}: {w.win_rate:.1f}%"
            await interaction.response.send_message(msg, ephemeral=True)

        @self.tree.command(name="add", description="Add wallet to track")
        async def add_slash(interaction: discord.Interaction, address: str):
            MAX_WALLETS = 10  # Max wallets per user

            if not is_valid_address(address):
                await interaction.response.send_message(
                    "Invalid address.", ephemeral=True
                )
                return

            # Check if already tracking
            existing = self.storage.get_wallet(address)
            if existing:
                await interaction.response.send_message(
                    f"Already tracking this wallet.", ephemeral=True
                )
                return

            # Check limit
            wallets = self.storage.list_wallets()
            if len(wallets) >= MAX_WALLETS:
                await interaction.response.send_message(
                    f"Limit reached ({MAX_WALLETS} wallets). Remove one first.",
                    ephemeral=True,
                )
                return

            self.storage.add_wallet(Wallet(address=address, nickname=address[:12] + "..."))
            await interaction.response.send_message(
                f"✅ Added `{address[:12]}...` to tracking!\nNow tracking {len(wallets) + 1}/{MAX_WALLETS} wallets.",
                ephemeral=True,
            )

        @self.tree.command(name="remove", description="Remove wallet from tracking")
        async def remove_slash(interaction: discord.Interaction, address: str):
            if not is_valid_address(address):
                await interaction.response.send_message(
                    "Invalid address.", ephemeral=True
                )
                return

            removed = self.storage.remove_wallet(address)
            if removed:
                wallets = self.storage.list_wallets()
                await interaction.response.send_message(
                    f"✅ Removed `{address[:12]}...`\nNow tracking {len(wallets)} wallets.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Wallet not found in tracking.", ephemeral=True
                )

        @self.tree.command(
            name="scan", description="Scan wallet for suspicious activity"
        )
        async def scan_slash(interaction: discord.Interaction, address: str):
            """Scan a wallet for insider trading indicators."""
            await interaction.response.defer(ephemeral=True)

            if not is_valid_address(address):
                await interaction.followup.send("Invalid address.", ephemeral=True)
                return

            try:
                from src.alerts.insider import InsiderDetector

                detector = InsiderDetector()
                result = detector.scan_wallet_for_anomalies(address)

                if "error" in result:
                    await interaction.followup.send(f"Error: {result['error']}")
                    return

                # Build response
                risk = result.get("freshness", {}).get("risk", "UNKNOWN")
                risk_emoji = {
                    "HIGH": "🔴",
                    "MEDIUM": "🟡",
                    "LOW": "🟢",
                    "UNKNOWN": "⚪",
                }.get(risk, "⚪")

                msg = f"**🔍 Wallet Scan: `{address[:12]}...`**\n\n"
                msg += f"{risk_emoji} **Risk Level:** {risk}\n"
                msg += f"📊 **Total Trades:** {result.get('freshness', {}).get('total_trades', 'N/A')}\n"
                msg += f"📈 **Open Positions:** {result.get('positions_count', 0)}\n"
                msg += f"📋 **Closed Trades:** {result.get('closed_count', 0)}\n\n"

                if risk == "HIGH":
                    msg += (
                        "⚠️ **WARNING:** This wallet appears to be NEW (few trades).\n"
                    )
                    msg += "Fresh wallets making large trades may indicate insider activity.\n\n"
                elif risk == "MEDIUM":
                    msg += "⚡ **Note:** Low trade count. Monitor for unusual activity.\n\n"

                msg += f"**Recommendation:** {result.get('recommendation', 'N/A')}\n"
                msg += f"\n_Use `/add {address}` to track this wallet_"

                await interaction.followup.send(msg, ephemeral=True)

            except Exception as e:
                await interaction.followup.send(f"Error: {str(e)[:100]}")

        @self.tree.command(name="ca", description="Scan meme coin contract address")
        async def ca_slash(interaction: discord.Interaction, address: str):
            """Scan a meme coin contract address for safety analysis."""
            await interaction.response.defer(ephemeral=True)

            # Clean address
            address = address.strip()
            if address.startswith("0x"):
                address = address[2:]  # Remove 0x prefix for some APIs

            try:
                from src.alerts.meme_scanner import MemeCoinScanner

                scanner = MemeCoinScanner()
                result = scanner.scan_token(address)

                if "error" in result:
                    await interaction.followup.send(f"Error: {result['error']}")
                    return

                safety = result.get("safety", {})
                risk = safety.get("risk", "UNKNOWN")
                score = safety.get("score", 0)

                risk_emoji = {
                    "LOW": "🟢",
                    "MEDIUM": "🟡",
                    "HIGH": "🔴",
                    "CRITICAL": "💀",
                    "UNKNOWN": "⚪",
                }.get(risk, "⚪")

                # Build response
                msg = f"**🪙 Token Scan: `{address[:16]}...`**\n\n"
                msg += (
                    f"{risk_emoji} **Risk:** {risk} | **Safety Score:** {score}/100\n\n"
                )

                # Liquidity
                liq = safety.get("liquidity_usd", 0)
                if liq:
                    msg += f"💧 **Liquidity:** ${liq:,.0f}\n"
                else:
                    msg += f"💧 **Liquidity:** N/A\n"

                # DexScreener data
                ds = result.get("dexscreener", {})
                if ds.get("found"):
                    price = ds.get("price", "N/A")
                    if price:
                        msg += f"💵 **Price:** ${price}\n"

                    vol = ds.get("volume24h")
                    if vol:
                        msg += f"📊 **24h Volume:** ${vol:,.0f}\n"

                    change = ds.get("priceChange24h")
                    if change is not None:
                        emoji = "🟢" if change >= 0 else "🔴"
                        msg += f"{emoji} **24h Change:** {change:+.1f}%\n"

                    pair = ds.get("pair", {})
                    base = pair.get("baseToken", {})
                    if base:
                        symbol = base.get("symbol", "N/A")
                        name = base.get("name", "N/A")
                        msg += f"🪙 **Token:** {name} ({symbol})\n"

                # Honeypot check
                hp = result.get("honeypot", {})
                if hp and hp.get("is_honeypot") is not None:
                    if hp.get("is_honeypot"):
                        msg += f"🚨 **Honeypot:** YES - {hp.get('reason', 'Cannot sell')}\n"
                    else:
                        msg += f"🛡️ **Honeypot:** No\n"
                    buy_tax = hp.get("buy_tax")
                    sell_tax = hp.get("sell_tax")
                    if buy_tax is not None or sell_tax is not None:
                        try:
                            bt = float(buy_tax) if buy_tax is not None else 0
                            st = float(sell_tax) if sell_tax is not None else 0
                            msg += f"📊 **Tax:** Buy {bt:.0f}% | Sell {st:.0f}%\n"
                        except (ValueError, TypeError):
                            msg += f"📊 **Tax:** Buy {buy_tax or '?'}% | Sell {sell_tax or '?'}%\n"
                    holders = hp.get("total_holders")
                    if holders is not None:
                        msg += f"👥 **Holders:** {holders:,}\n"
                    if hp.get("risk") and hp.get("risk") != "unknown":
                        msg += f"⚠️ **Honeypot Risk:** {hp.get('risk', '')}\n"

                # Risk factors
                factors = safety.get("factors", [])
                if factors:
                    msg += "\n⚠️ **Risk Factors:**\n"
                    for f in factors[:5]:
                        msg += f"• {f}\n"

                # Links (ensure 0x prefix for URLs)
                addr_hex = address if address.startswith("0x") else f"0x{address}"
                msg += "\n**🔗 Links:**\n"
                msg += f"[DexScreener](https://dexscreener.com/search?q={addr_hex}) | "
                msg += f"[DexTools](https://www.dextools.io/app/en/pair-explorer/{addr_hex})"

                await interaction.followup.send(msg[:2000], ephemeral=True)

            except Exception as e:
                await interaction.followup.send(f"Error: {str(e)[:200]}")

        # === MESSAGE COMMANDS (fallback) ===
        @self.command(name="bankr")
        async def bankr_msg(ctx, *, question: str):
            await ctx.message.reply("Thinking...")
            await self._handle_ai_message(ctx, question, "bankr")

        @self.command(name="ask")
        async def ask_msg(ctx, *, question: str):
            await ctx.message.reply("Thinking...")
            await self._handle_ai_message(ctx, question, "ask")

        @self.command(name="status")
        async def status_msg(ctx):
            wallets = self.storage.list_wallets()
            smart_money = [w for w in wallets if w.is_smart_money]
            msg = f"Tracking {len(wallets)} wallets ({len(smart_money)} smart)"
            if wallets:
                msg += "\n\nTop:"
                for w in sorted(wallets, key=lambda x: x.win_rate, reverse=True)[:5]:
                    msg += f"\n• {w.nickname}: {w.win_rate:.1f}%"
            await ctx.message.reply(msg)

        @self.command(name="add")
        async def add_msg(ctx, address: str):
            MAX_WALLETS = 10
            if not is_valid_address(address):
                await ctx.message.reply("Invalid address.")
                return
            existing = self.storage.get_wallet(address)
            if existing:
                await ctx.message.reply("Already tracking this wallet.")
                return
            wallets = self.storage.list_wallets()
            if len(wallets) >= MAX_WALLETS:
                await ctx.message.reply(
                    f"Limit reached ({MAX_WALLETS} wallets). Remove one first."
                )
                return
            self.storage.add_wallet(Wallet(address=address, nickname=address[:12] + "..."))
            await ctx.message.reply(f"Added: {address[:12]}...")

    async def _handle_ai(self, interaction, question: str, command_name: str):
        """Handle AI query via slash command."""
        try:
            if not self.bankr or not self.bankr.is_configured():
                await interaction.response.send_message(
                    "Bankr not configured. Add BANKR_API_KEY to .env", ephemeral=True
                )
                return

            print(f"Bankr query: {question[:50]}...")

            # MUST respond within 3 seconds - defer extends to 15 min
            await interaction.response.defer(ephemeral=True)

            job_id, error_msg = self.bankr.send_prompt(question)
            print(f"Job ID: {job_id}")

            if not job_id:
                msg = error_msg or "❌ Failed to submit. Try again."
                await interaction.edit_original_response(content=msg)
                return

            # Poll every 2s, max 60 attempts (~2 min) per Bankr recommendation
            for i in range(60):
                await asyncio.sleep(2)
                status = self.bankr.get_job_status(job_id)
                print(f"Poll {i + 1}: {status.get('status') if status else 'None'}")

                if status and status.get("status") == "completed":
                    result = status.get("result", status.get("response", ""))
                    if result:
                        await interaction.edit_original_response(content=f"✅ {result[:2000]}")
                    else:
                        await interaction.edit_original_response(content="Got empty response.")
                    return
                elif status and status.get("status") == "cancelled":
                    await interaction.edit_original_response(content="Job was cancelled.")
                    return
                elif status and status.get("status") == "failed":
                    err = status.get("error", "Unknown error")
                    await interaction.edit_original_response(content=f"❌ Query failed: {err[:200]}")
                    return

            await interaction.edit_original_response(content="⏰ Timeout. Try simpler question.")
        except Exception as e:
            print(f"Bankr error: {e}")
            try:
                await interaction.edit_original_response(content=f"Error: {str(e)[:200]}")
            except Exception:
                pass

    async def _handle_ai_message(self, ctx, question: str, command_name: str):
        """Handle AI query via message command."""
        try:
            if not self.bankr or not self.bankr.is_configured():
                await ctx.message.reply("Bankr not configured. Add BANKR_API_KEY to .env")
                return

            job_id, err = self.bankr.send_prompt(question)
            if not job_id:
                await ctx.message.reply(err or "Failed to submit. Check API.")
                return

            for i in range(45):
                await asyncio.sleep(1.5)
                status = self.bankr.get_job_status(job_id)
                if status and status.get("status") == "completed":
                    result = status.get("result", status.get("response", ""))
                    await ctx.message.reply(result[:2000] if result else "No result")
                    return
                elif status and status.get("status") == "failed":
                    err = status.get("error", "Unknown")
                    await ctx.message.reply(f"Query failed: {err[:100]}")
                    return
                elif status and status.get("status") == "cancelled":
                    await ctx.message.reply("Job was cancelled.")
                    return

            await ctx.message.reply("Timeout - try simpler question.")
        except Exception as e:
            await ctx.message.reply(f"Error: {str(e)[:200]}")

    async def setup_hook(self):
        """Sync commands on startup."""
        await self.tree.sync()
        print(
            f"Discord slash commands synced: {[c.name for c in self.tree.get_commands()]}"
        )

    async def on_ready(self):
        """Called when bot is ready."""
        print(f"Discord bot ready: {self.user}")

    async def on_message(self, message):
        """Handle messages - respond to mentions and scan for token addresses."""
        if message.author == self.user:
            return

        content_lower = message.content.lower()

        # Check if bot is mentioned OR user types @predictionsuite
        bot_mentioned = self.user in message.mentions
        predictionsuite_mentioned = (
            "predictionsuite" in content_lower or "@predictionsuite" in content_lower
        )

        if bot_mentioned or predictionsuite_mentioned:
            # Remove any mention from content
            question = message.content
            for mention in message.mentions:
                question = question.replace(f"@{mention.name}", "").strip()
            question = question.replace("@predictionsuite", "").strip()

            if not question:
                await message.reply(
                    "Hi! Use /bankr or ask me anything about crypto/markets."
                )
                return

            await message.reply("Thinking...")

            if not self.bankr or not self.bankr.is_configured():
                await message.reply("Bankr not configured. Add BANKR_API_KEY to .env")
                return

            job_id, _ = self.bankr.send_prompt(question)
            if job_id:
                # Poll with better timeout and backoff
                result = await self._wait_for_bankr_job(job_id, timeout_seconds=60)
                if result:
                    await message.reply(result[:2000] if len(result) > 2000 else result)
                else:
                    await message.reply("Bankr timed out. Try again later.")
            else:
                await message.reply("Failed to submit to Bankr. Check API key.")
            return

        # Token Scanner: detect addresses in message
        content = message.content
        import re

        addr_pattern = r"0x[a-fA-F0-9]{40}"
        addresses = re.findall(addr_pattern, content)

        if addresses and not message.author.bot:
            for addr in addresses[:2]:  # Max 2 per message
                await self._scan_address(message, addr)

        # Check for market/condition IDs (long hex)
        condition_pattern = r"0x[a-fA-F0-9]{64}"
        conditions = re.findall(condition_pattern, content)

        if conditions and not message.author.bot:
            for cond in conditions[:1]:  # Max 1 per message
                await self._scan_market(message, cond)

        await self.process_commands(message)

    async def _wait_for_bankr_job(self, job_id: str, timeout_seconds: int = 60) -> str:
        """Wait for Bankr job with exponential backoff."""
        import asyncio
        import time

        start_time = time.monotonic()
        poll_interval = 1.0  # Start at 1 second

        while True:
            await asyncio.sleep(poll_interval)

            elapsed = time.monotonic() - start_time
            if elapsed > timeout_seconds:
                return None

            status = self.bankr.get_job_status(job_id)
            if not status:
                continue

            if status.get("status") == "completed":
                return status.get("response") or status.get("result", "No result")
            elif status.get("status") == "failed":
                return f"Job failed: {status.get('error', 'Unknown error')}"
            elif status.get("status") == "cancelled":
                return "Job was cancelled."

            # Exponential backoff, max 5 seconds
            poll_interval = min(poll_interval * 1.5, 5.0)

    async def _scan_address(self, message, address: str):
        """Scan a wallet address - Lute-style detailed view."""
        try:
            await message.reply(f"🔍 Scanning `{address[:10]}...`")

            # Get wallet stats from Polymarket Data API
            try:
                # Get closed positions for stats
                resp = requests.get(
                    "https://data-api.polymarket.com/closed-positions",
                    params={"user": address, "limit": 50},
                    timeout=10,
                )
                closed = resp.json() if resp.status_code == 200 else []

                # Calculate stats from closed positions
                total_pnl = 0
                total_volume = 0
                wins = 0
                for p in closed:
                    total_pnl += float(p.get("realizedPnl", 0) or 0)
                    total_volume += float(p.get("totalBought", 0) or 0) * float(
                        p.get("avgPrice", 0) or 0
                    )
                    if float(p.get("realizedPnl", 0) or 0) > 0:
                        wins += 1

                total_trades = len(closed)
                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            except Exception as e:
                total_trades = 0
                total_pnl = 0
                total_volume = 0
                win_rate = 0

            # Get current positions
            try:
                resp = requests.get(
                    "https://data-api.polymarket.com/positions",
                    params={"user": address, "limit": 20},
                    timeout=10,
                )
                positions = resp.json() if resp.status_code == 200 else []
            except Exception:
                positions = []

            # Build response
            addr_short = address[:12] + "..."

            # Format
            try:
                pnl_str = f"${total_pnl:+,.0f}" if total_pnl else "$0"
            except Exception:
                pnl_str = "$0"

            try:
                vol_str = f"${total_volume:,.0f}" if total_volume else "$0"
            except Exception:
                vol_str = "$0"

            wr_emoji = "🟢" if win_rate >= 60 else ("🟡" if win_rate >= 50 else "🔴")

            msg = f"**👤 Wallet:** `{addr_short}`\n\n"
            msg += f"📊 **Stats:** {total_trades} trades | {wr_emoji} WR: {win_rate:.1f}%\n"
            msg += f"💰 **Volume:** {vol_str} | PnL: {pnl_str}\n"
            msg += f"📈 **Open Positions:** {len(positions)}\n\n"

            if positions:
                msg += "**Active Positions:**\n"
                for p in positions[:5]:
                    q = p.get("title", p.get("question", "Unknown"))[:25]
                    outcome = p.get("outcome", "?")
                    size = float(p.get("size", 0) or 0)
                    try:
                        size_str = f"${size:,.0f}"
                    except Exception:
                        size_str = str(size)
                    emoji = "🟢" if outcome.upper() == "YES" else "🔴"
                    msg += f"{emoji} {outcome}: {q}... ({size_str})\n"

            # Add Polymarket profile link
            msg += f"\n[View on Polymarket](https://polymarket.com/profile/{address})"

            await message.reply(msg[:2000])

        except Exception as e:
            await message.reply(f"Error scanning: {str(e)[:100]}")

    async def _scan_market(self, message, condition_id: str):
        """Scan a market by condition ID."""
        try:
            await message.reply(f"Scanning market...")

            # Try to get market details
            market = self.agent.get_market_info(condition_id)

            if market:
                q = market.get("question", "Unknown")
                vol = float(market.get("volume", 0) or 0)
                prices = market.get("outcomePrices", [])

                msg = f"**{q[:100]}**\n"
                msg += f"Volume: ${vol:,.0f}\n"

                if prices and len(prices) >= 2:
                    try:
                        yes_p = (
                            float(prices[0])
                            if isinstance(prices[0], (int, float))
                            else float(prices[0].strip('"'))
                        )
                        no_p = (
                            float(prices[1])
                            if isinstance(prices[1], (int, float))
                            else float(prices[1].strip('"'))
                        )
                        msg += f"YES: {yes_p * 100:.0f}% | NO: {no_p * 100:.0f}%"
                    except Exception:
                        pass

                await message.reply(msg)
            else:
                await message.reply(f"Market not found for `{condition_id[:15]}...`")
        except Exception as e:
            await message.reply(f"Error: {str(e)[:100]}")

    async def on_interaction(self, interaction):
        """Debug all interactions."""
        print(f"Interaction: {interaction.type} - {interaction.command}")

    def run_bot(self):
        print("Starting Discord bot...")
        self.run(self.token)
