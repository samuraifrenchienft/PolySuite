"""Discord bot for PolySuite - hybrid approach with both slash and message commands."""

import discord
from discord import app_commands
from discord.ext import commands
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.utils import is_valid_eth_address, is_valid_solana_address, sanitize_nickname
from src.agent import Agent
from src.config import Config
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
        self.agent = Agent(config=config, storage=storage, api_factory=api_factory)

        # Groq AI for chat (primary)
        self.groq_key = os.getenv("Groq_api_key") or os.getenv("GROQ_API_KEY")
        # OpenRouter (backup)
        self.openrouter_key = os.getenv("Openrouter_api_key") or os.getenv(
            "OPENROUTER_API_KEY"
        )

        # === SLASH COMMANDS ===
        @self.tree.command(
            name="ask",
            description="Ask AI about markets, crypto, or anything",
        )
        async def ask_slash(interaction: discord.Interaction, question: str):
            await self._handle_ai(interaction, question.strip())

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
        async def add_slash(interaction: discord.Interaction, address: str, nickname: str = None):
            MAX_WALLETS = 10  # Max wallets per user

            if not is_valid_eth_address(address):
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

            # Use provided nickname or create a default one (sanitized)
            raw_nick = nickname if nickname else address[:12] + "..."
            final_nickname = sanitize_nickname(raw_nick) or address[:12] + "..."

            self.storage.add_wallet(
                Wallet(address=address, nickname=final_nickname)
            )
            await interaction.response.send_message(
                f"✅ Added `{final_nickname}` to tracking!\nNow tracking {len(wallets) + 1}/{MAX_WALLETS} wallets.",
                ephemeral=True,
            )

        @self.tree.command(name="remove", description="Remove wallet from tracking")
        async def remove_slash(interaction: discord.Interaction, address: str):
            if not is_valid_eth_address(address):
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
            name="bankr",
            description="Ask Bankr AI (balance, prices, trades) - may take up to 2 min",
        )
        async def bankr_slash(interaction: discord.Interaction, question: str):
            """Bankr AI query with defer + poll. Runs sync Bankr calls in thread to avoid blocking Discord."""
            await interaction.response.defer(ephemeral=True)
            try:
                from src.config import get_bankr_client

                bankr = get_bankr_client(self.config.bankr_api_key)
                if not bankr or not bankr.is_configured():
                    await interaction.edit_original_response(
                        content="❌ Bankr not configured. Add BANKR_API_KEY to .env"
                    )
                    return

                await interaction.edit_original_response(content="⏳ Sending to Bankr...")

                # Run blocking send_prompt in thread (avoids blocking Discord event loop)
                job_id, err = await asyncio.to_thread(
                    bankr.send_prompt, question.strip()
                )
                if err:
                    await interaction.edit_original_response(content=f"❌ {err}")
                    return
                if not job_id:
                    await interaction.edit_original_response(
                        content="❌ Failed to submit. Check API key."
                    )
                    return

                # Poll 2s, max 60 attempts (2 min)
                for attempt in range(60):
                    await asyncio.sleep(2)
                    status = await asyncio.to_thread(bankr.get_job_status, job_id)
                    if status:
                        if status.get("status") == "completed":
                            result = (
                                status.get("response")
                                or status.get("result")
                                or ""
                            ).strip()
                            if not result:
                                result = "Bankr returned empty response."
                            await interaction.edit_original_response(
                                content=f"🤖 **Bankr:** {result[:1900]}"
                            )
                            return
                        if status.get("status") == "failed":
                            await interaction.edit_original_response(
                                content="❌ Bankr query failed."
                            )
                            return
                    if attempt % 5 == 4:
                        await interaction.edit_original_response(
                            content=f"⏳ Waiting for Bankr... ({(attempt + 1) * 2}s)"
                        )

                await interaction.edit_original_response(
                    content="❌ Timed out after 2 min. Try a simpler question."
                )
            except discord.errors.NotFound:
                pass  # Interaction expired or was deleted
            except Exception as e:
                print(f"[Discord/bankr] Error: {e}")
                try:
                    await interaction.edit_original_response(
                        content="An error occurred. Please try again."
                    )
                except discord.errors.NotFound:
                    pass

        @self.tree.command(
            name="markets",
            description="Show top active markets by volume",
        )
        @app_commands.describe(limit="Number of markets to show (1-15)")
        async def markets_slash(interaction: discord.Interaction, limit: int = 5):
            """Show top Polymarket markets."""
            await interaction.response.defer(ephemeral=True)
            try:
                api = self.api_factory.get_polymarket_api()
                markets = api.get_active_markets(limit=min(limit, 15))
                if not markets:
                    await interaction.edit_original_response(
                        content="No markets found."
                    )
                    return
                msg = "**📊 Top Markets**\n\n"
                for m in markets[:limit]:
                    q = (m.get("question") or "Unknown")[:50]
                    vol = float(m.get("volume") or 0)
                    msg += f"• ${vol:,.0f} - {q}...\n"
                msg += "\n[Polymarket](https://polymarket.com)"
                await interaction.edit_original_response(content=msg[:2000])
            except Exception as e:
                print(f"[Discord/markets] Error: {e}")
                await interaction.edit_original_response(
                    content="Could not fetch markets. Please try again."
                )

        @self.tree.command(
            name="scan", description="Scan wallet for suspicious activity"
        )
        async def scan_slash(interaction: discord.Interaction, address: str):
            """Scan a wallet for insider trading indicators."""
            await interaction.response.defer(ephemeral=True)

            if not is_valid_eth_address(address):
                await interaction.followup.send("Invalid address.", ephemeral=True)
                return

            try:
                from src.alerts.insider import InsiderDetector

                detector = InsiderDetector()
                result = detector.scan_wallet_for_anomalies(address)

                if "error" in result:
                    print(f"[Discord/scan] Detector error: {result['error']}")
                    await interaction.followup.send("Scan failed. Please try again.")
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
                msg += f"📋 **Closed Trades:** {result.get('closed_count', 0)}\n"

                # Categories breakdown
                cats = result.get("categories", {})
                if cats:
                    cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(cats.items(), key=lambda x: -x[1])[:5])
                    msg += f"🏷️ **Categories:** {cat_str}\n"

                # Recent trades
                recent = result.get("recent_trades", [])
                if recent:
                    msg += "\n**Recent Trades:**\n"
                    for t in recent[:3]:
                        q = t.get("question", "?")[:35]
                        side = t.get("side", "?")
                        size = t.get("size", 0)
                        msg += f"• {side} ${size:,.0f} → {q}...\n"
                msg += "\n"

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
                print(f"[Discord/scan] Error: {e}")
                await interaction.followup.send("Scan failed. Please try again.")

        @self.tree.command(name="ca", description="Scan meme coin contract address")
        async def ca_slash(interaction: discord.Interaction, address: str):
            """Scan a meme coin contract address for safety analysis."""
            await interaction.response.defer(ephemeral=True)

            # Clean and validate address (MED-003)
            address = address.strip()
            if address.startswith("0x"):
                if not is_valid_eth_address(address):
                    await interaction.followup.send("Invalid Ethereum address.", ephemeral=True)
                    return
                address = address[2:]  # Remove 0x prefix for some APIs
            elif not is_valid_solana_address(address):
                await interaction.followup.send("Invalid address format.", ephemeral=True)
                return

            try:
                from src.alerts.meme_scanner import MemeCoinScanner

                scanner = MemeCoinScanner()
                result = scanner.scan_token(address)

                if "error" in result:
                    print(f"[Discord/ca] Scanner error: {result['error']}")
                    await interaction.followup.send("Token scan failed. Please try again.")
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
                print(f"[Discord/ca] Error: {e}")
                await interaction.followup.send("Token scan failed. Please try again.")

        # === MESSAGE COMMANDS (fallback) ===
        @self.command(name="ask")
        async def ask_msg(ctx, *, question: str):
            await ctx.message.reply("🤔 Thinking...")
            await self._handle_ai_message(ctx, question)

        @self.command(name="ai")
        async def ai_msg(ctx, *, question: str):
            await ctx.message.reply("🤔 Thinking...")
            await self._handle_ai_message(ctx, question)

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
        async def add_msg(ctx, *, args: str = None):
            MAX_WALLETS = 10
            if not args:
                await ctx.message.reply("Usage: !add <address> [nickname]")
                return

            parts = args.split()
            address = parts[0]
            raw_nick = parts[1] if len(parts) > 1 else address[:12] + "..."
            nickname = sanitize_nickname(raw_nick) or address[:12] + "..."

            if not is_valid_eth_address(address):
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

            self.storage.add_wallet(Wallet(address=address, nickname=nickname))
            await ctx.message.reply(f"Added: {nickname} (`{address[:8]}...`)")

    async def _handle_ai(self, interaction, question: str):
        """Handle AI query via slash command - uses Groq."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Use Groq AI
            response = self._call_groq(question)

            if response:
                await interaction.edit_original_response(
                    content=f"🤖 {response[:2000]}"
                )
            else:
                await interaction.edit_original_response(
                    content="AI temporarily unavailable. Try again later."
                )

        except Exception as e:
            print(f"[Discord/AI] Error: {e}")
            await interaction.edit_original_response(
                content="AI temporarily unavailable. Please try again."
            )

    def _call_groq(self, message: str) -> str:
        """Call Groq AI."""
        # System prompt
        system_prompt = """You are Prediction Suite AI Assistant. Help users understand prediction markets (Polymarket, Kalshi, Jupiter). Be concise, friendly, no financial advice."""

        # Try Groq
        if self.groq_key:
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 500,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"[Discord-Groq] Error: {e}")

        # Fallback to OpenRouter
        if self.openrouter_key:
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "qwen/qwen3-vl-30b-a3b-thinking",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message},
                        ],
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"[Discord-OpenRouter] Error: {e}")

        return None

    async def _handle_ai_message(self, ctx, question: str, command_name: str):
        """Handle AI query via message command - uses Groq now."""
        try:
            response = self._call_groq(question)
            if response:
                await ctx.message.reply(f"🤖 {response[:2000]}")
            else:
                await ctx.message.reply("AI unavailable. Try again later.")
        except Exception as e:
            print(f"[Discord/AI-msg] Error: {e}")
            await ctx.message.reply("AI temporarily unavailable. Please try again.")

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
                await message.reply("Hi! Use /ask or /ai to chat with me.")
                return

            await message.reply("🤔 Thinking...")

            # Use Groq AI
            response = self._call_groq(question)
            if response:
                await message.reply(f"🤖 {response[:2000]}")
            else:
                await message.reply("AI unavailable. Try again later.")
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
            print(f"[Discord/scan-addr] Error: {e}")
            await message.reply("Scan failed. Please try again.")

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
            print(f"[Discord/scan-market] Error: {e}")
            await message.reply("Market scan failed. Please try again.")

    async def on_interaction(self, interaction):
        """Debug all interactions."""
        print(f"Interaction: {interaction.type} - {interaction.command}")

    def run_bot(self):
        print("Starting Discord bot...")
        self.run(self.token)
