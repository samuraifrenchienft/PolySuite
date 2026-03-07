"""Discord bot for PolySuite - hybrid approach with both slash and message commands."""

import discord
from discord import app_commands
from discord.ext import commands
from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.utils import is_valid_eth_address, is_valid_solana_address, sanitize_nickname
from src.config import Config
import asyncio
import json
import os
import requests
from pathlib import Path


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

        # Groq AI for chat (primary)
        self.groq_key = os.getenv("Groq_api_key") or os.getenv("GROQ_API_KEY")
        # OpenRouter (backup)
        self.openrouter_key = os.getenv("Openrouter_api_key") or os.getenv(
            "OPENROUTER_API_KEY"
        )

        # === SLASH COMMANDS ===
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

            lines = [f"**{header}**"]
            for i, w in enumerate(wallets[:limit], 1):
                name = w.get("nickname") or (w.get("address", "")[:10] + "...")
                rel = float(w.get("reliability_score", 0) or 0)
                streak = int(w.get("current_win_streak", 0) or 0)
                recent = float(w.get("recent_win_rate", 0) or 0)
                lines.append(
                    f"{i}. `{name}` | Rel {rel:.1f} | Streak {streak} | Recent {recent:.1f}%"
                )
            return "\n".join(lines)

        @self.tree.command(
            name="ask",
            description="Ask AI about markets, crypto, or anything",
        )
        async def ask_slash(interaction: discord.Interaction, question: str):
            await interaction.response.send_message(
                "Chat AI is disabled for performance. Use your external AI agent.",
                ephemeral=True,
            )

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

        @self.tree.command(
            name="top_reliable_wallets", description="Show top vetted reliable traders"
        )
        async def top_reliable_wallets_slash(
            interaction: discord.Interaction, limit: int = 5
        ):
            msg = _format_vetted_rankings("reliable", limit)
            await interaction.response.send_message(msg[:2000], ephemeral=True)

        @self.tree.command(
            name="top_streak_wallets", description="Show top vetted win-streak traders"
        )
        async def top_streak_wallets_slash(
            interaction: discord.Interaction, limit: int = 5
        ):
            msg = _format_vetted_rankings("streak", limit)
            await interaction.response.send_message(msg[:2000], ephemeral=True)

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

        # === COPY TRADING (Phase D) ===
        copy_group = app_commands.Group(name="copy", description="Copy trading commands")

        @copy_group.command(name="add", description="Add wallet to copy targets")
        @app_commands.describe(address="Wallet address to copy", nickname="Optional nickname")
        async def copy_add_slash(interaction: discord.Interaction, address: str, nickname: str = None):
            if not is_valid_eth_address(address):
                await interaction.response.send_message("Invalid address.", ephemeral=True)
                return
            try:
                from src.copy import add_copy_target
                ok = add_copy_target(address, nickname or "")
                if ok:
                    from src.copy import list_copy_targets
                    targets = list_copy_targets()
                    await interaction.response.send_message(
                        f"Added `{address[:12]}...` to copy targets ({len(targets)} total).",
                        ephemeral=True,
                    )
                else:
                    from src.copy import list_copy_targets
                    if any(t.get("address", "").lower() == address.lower() for t in list_copy_targets()):
                        await interaction.response.send_message("Already in copy targets.", ephemeral=True)
                    else:
                        await interaction.response.send_message("Limit reached (20 targets). Remove one first.", ephemeral=True)
            except Exception as e:
                print(f"[Discord/copy add] Error: {e}")
                await interaction.response.send_message("Failed to add. Please try again.", ephemeral=True)

        @copy_group.command(name="remove", description="Remove wallet from copy targets")
        @app_commands.describe(address="Wallet address to remove")
        async def copy_remove_slash(interaction: discord.Interaction, address: str):
            if not is_valid_eth_address(address):
                await interaction.response.send_message("Invalid address.", ephemeral=True)
                return
            try:
                from src.copy import remove_copy_target, list_copy_targets
                ok = remove_copy_target(address)
                if ok:
                    targets = list_copy_targets()
                    await interaction.response.send_message(
                        f"Removed `{address[:12]}...` ({len(targets)} targets left).",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message("Not in copy targets.", ephemeral=True)
            except Exception as e:
                print(f"[Discord/copy remove] Error: {e}")
                await interaction.response.send_message("Failed to remove. Please try again.", ephemeral=True)

        @copy_group.command(name="list", description="List copy targets")
        async def copy_list_slash(interaction: discord.Interaction):
            try:
                from src.copy import list_copy_targets
                targets = list_copy_targets()
                if not targets:
                    await interaction.response.send_message("No copy targets. Use `/copy add` to add wallets.", ephemeral=True)
                    return
                msg = f"**Copy targets ({len(targets)})**\n\n"
                for t in targets[:15]:
                    addr = t.get("address", "?")[:10] + "..."
                    nick = t.get("nickname", "")
                    msg += f"• {nick or addr} (`{addr}`)\n"
                if len(targets) > 15:
                    msg += f"\n... and {len(targets) - 15} more"
                await interaction.response.send_message(msg[:2000], ephemeral=True)
            except Exception as e:
                print(f"[Discord/copy list] Error: {e}")
                await interaction.response.send_message("Failed to list. Please try again.", ephemeral=True)

        @copy_group.command(name="kill", description="Kill switch: immediately pause all copy trading")
        async def copy_kill_slash(interaction: discord.Interaction):
            try:
                if hasattr(self.config, "set"):
                    self.config.set("copy_pause", True)
                    if hasattr(self.config, "save"):
                        self.config.save()
                else:
                    self.config["copy_pause"] = True
                await interaction.response.send_message("Copy trading PAUSED (kill switch). Use `/copy resume` to re-enable.", ephemeral=True)
            except Exception as e:
                print(f"[Discord/copy kill] Error: {e}")
                await interaction.response.send_message("Failed to save. Check config.", ephemeral=True)

        @copy_group.command(name="resume", description="Resume copy trading after kill switch")
        async def copy_resume_slash(interaction: discord.Interaction):
            try:
                if hasattr(self.config, "set"):
                    self.config.set("copy_pause", False)
                    if hasattr(self.config, "save"):
                        self.config.save()
                else:
                    self.config["copy_pause"] = False
                await interaction.response.send_message("Copy trading resumed.", ephemeral=True)
            except Exception as e:
                print(f"[Discord/copy resume] Error: {e}")
                await interaction.response.send_message("Failed to save. Check config.", ephemeral=True)

        @copy_group.command(name="settings", description="View copy trading safety settings")
        async def copy_settings_slash(interaction: discord.Interaction):
            try:
                cfg = self.config.config if hasattr(self.config, "config") else self.config
                msg = "**Copy settings:**\n"
                msg += f"Max order: ${cfg.get('copy_max_order_usd', 100)}\n"
                msg += f"Size multiplier: {cfg.get('copy_size_multiplier', 1.0)}\n"
                msg += f"Throttle: {cfg.get('copy_max_trades_per_minute', 0) or 'off'} per min\n"
                msg += f"Risk reduction: after {cfg.get('copy_reduce_multiplier_after_trades', 0) or 0} trades -> {cfg.get('copy_reduced_multiplier', 0.5)}x\n"
                msg += f"Freeze: after {cfg.get('copy_freeze_after_trades', 0) or 0} trades for {cfg.get('copy_freeze_duration_minutes', 60)} min\n"
                msg += f"Fee: {cfg.get('copy_fee_pct', 0.77)}% | Referral discount: {cfg.get('copy_referral_discount_pct', 10)}%\n"
                msg += f"Paused: {cfg.get('copy_pause', False)}"
                await interaction.response.send_message(msg[:2000], ephemeral=True)
            except Exception as e:
                print(f"[Discord/copy settings] Error: {e}")
                await interaction.response.send_message("Failed.", ephemeral=True)

        @self.tree.command(name="copystatus", description="Copy trading status")
        async def copystatus_slash(interaction: discord.Interaction):
            try:
                from src.copy import list_copy_targets
                targets = list_copy_targets()
                enabled = self.config.get("copy_enabled", False)
                dry_run = self.config.get("copy_dry_run", True)
                msg = f"**Copy trading:** {'ON' if enabled else 'OFF'}\n"
                msg += f"**Dry run:** {'Yes' if dry_run else 'No (live)'}\n"
                msg += f"**Targets:** {len(targets)}\n"
                if targets:
                    msg += "\nTop: " + ", ".join((t.get("nickname") or t.get("address", "")[:10]) for t in targets[:5])
                await interaction.response.send_message(msg[:2000], ephemeral=True)
            except Exception as e:
                print(f"[Discord/copystatus] Error: {e}")
                await interaction.response.send_message("Failed. Please try again.", ephemeral=True)

        self.tree.add_command(copy_group)

        # === CONNECT (credential storage for copy trading) ===
        class PolymarketConnectModal(discord.ui.Modal, title="Connect Polymarket"):
            api_key = discord.ui.TextInput(label="API Key", placeholder="From polymarket.com/settings", max_length=255, required=True)
            api_secret = discord.ui.TextInput(label="API Secret", placeholder="API secret", max_length=255, required=True, style=discord.TextStyle.short)
            api_passphrase = discord.ui.TextInput(label="API Passphrase", placeholder="API passphrase", max_length=255, required=True, style=discord.TextStyle.short)

            def __init__(self, user_id: int):
                super().__init__()
                self.user_id = str(user_id)

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    from src.auth.credential_store import store_credentials
                    store_credentials(self.user_id, "polymarket", {
                        "api_key": self.api_key.value.strip(),
                        "api_secret": self.api_secret.value.strip(),
                        "api_passphrase": self.api_passphrase.value.strip(),
                    })
                    await interaction.response.send_message("Polymarket credentials saved.", ephemeral=True)
                except RuntimeError:
                    await interaction.response.send_message("Credential storage not configured.", ephemeral=True)
                except Exception as e:
                    print(f"[Discord/connect polymarket] Error: {type(e).__name__}")
                    await interaction.response.send_message("Failed to save. Try again.", ephemeral=True)

        class KalshiConnectModal(discord.ui.Modal, title="Connect Kalshi"):
            api_key_id = discord.ui.TextInput(label="API Key ID", placeholder="From kalshi.com/settings/api", max_length=255, required=True)
            private_key = discord.ui.TextInput(label="Private Key (PEM)", placeholder="-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----", max_length=4000, required=True, style=discord.TextStyle.paragraph)

            def __init__(self, user_id: int):
                super().__init__()
                self.user_id = str(user_id)

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    from src.auth.credential_store import store_credentials
                    pem = self.private_key.value.strip().replace("\\n", "\n")
                    store_credentials(self.user_id, "kalshi", {"api_key_id": self.api_key_id.value.strip(), "private_key_pem": pem})
                    await interaction.response.send_message("Kalshi credentials saved.", ephemeral=True)
                except RuntimeError:
                    await interaction.response.send_message("Credential storage not configured.", ephemeral=True)
                except Exception as e:
                    print(f"[Discord/connect kalshi] Error: {type(e).__name__}")
                    await interaction.response.send_message("Failed to save. Try again.", ephemeral=True)

        connect_group = app_commands.Group(name="connect", description="Connect Polymarket or Kalshi for copy trading")

        @connect_group.command(name="polymarket", description="Connect Polymarket API credentials")
        async def connect_polymarket_slash(interaction: discord.Interaction):
            modal = PolymarketConnectModal(interaction.user.id)
            await interaction.response.send_modal(modal)

        @connect_group.command(name="kalshi", description="Connect Kalshi API credentials")
        async def connect_kalshi_slash(interaction: discord.Interaction):
            modal = KalshiConnectModal(interaction.user.id)
            await interaction.response.send_modal(modal)

        self.tree.add_command(connect_group)

        # === MENU (buttons for all options) ===
        class MenuView(discord.ui.View):
            def __init__(self, bot_self):
                super().__init__(timeout=300)
                self._bot = bot_self

            @discord.ui.button(label="Status", style=discord.ButtonStyle.primary, row=0)
            async def btn_status(self, interaction: discord.Interaction, button: discord.ui.Button):
                wallets = self._bot.storage.list_wallets()
                smart = [w for w in wallets if w.is_smart_money]
                msg = f"Tracking {len(wallets)} wallets ({len(smart)} smart)"
                if wallets:
                    msg += "\n\nTop: " + ", ".join(f"{w.nickname}: {w.win_rate:.1f}%" for w in sorted(wallets, key=lambda x: x.win_rate, reverse=True)[:5])
                await interaction.response.send_message(msg, ephemeral=True)

            @discord.ui.button(label="Copy status", style=discord.ButtonStyle.secondary, row=0)
            async def btn_copy_status(self, interaction: discord.Interaction, button: discord.ui.Button):
                try:
                    from src.copy import list_copy_targets
                    targets = list_copy_targets()
                    enabled = self._bot.config.get("copy_enabled", False)
                    dry = self._bot.config.get("copy_dry_run", True)
                    await interaction.response.send_message(f"Copy: {'ON' if enabled else 'OFF'} | Dry run: {'Yes' if dry else 'No'}\nTargets: {len(targets)}", ephemeral=True)
                except Exception:
                    await interaction.response.send_message("Failed.", ephemeral=True)

            @discord.ui.button(label="Add wallet", style=discord.ButtonStyle.success, row=1)
            async def btn_add(self, interaction: discord.Interaction, button: discord.ui.Button):
                class AddModal(discord.ui.Modal, title="Add Wallet"):
                    addr = discord.ui.TextInput(label="Address", placeholder="0x...", max_length=42, required=True)
                    nick = discord.ui.TextInput(label="Nickname", placeholder="Optional", max_length=50, required=False)
                    def __init__(self, storage):
                        super().__init__()
                        self._storage = storage
                    async def on_submit(self, i: discord.Interaction):
                        if not is_valid_eth_address(self.addr.value.strip()):
                            await i.response.send_message("Invalid address.", ephemeral=True)
                            return
                        if self._storage.get_wallet(self.addr.value.strip()):
                            await i.response.send_message("Already tracking.", ephemeral=True)
                            return
                        if len(self._storage.list_wallets()) >= 10:
                            await i.response.send_message("Limit (10) reached.", ephemeral=True)
                            return
                        nick = sanitize_nickname(self.nick.value.strip()) or self.addr.value[:12] + "..."
                        self._storage.add_wallet(Wallet(address=self.addr.value.strip(), nickname=nick))
                        await i.response.send_message(f"Added {nick}.", ephemeral=True)
                await interaction.response.send_modal(AddModal(self._bot.storage))

            @discord.ui.button(label="Remove wallet", style=discord.ButtonStyle.danger, row=1)
            async def btn_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
                class RemoveModal(discord.ui.Modal, title="Remove Wallet"):
                    addr = discord.ui.TextInput(label="Address", placeholder="0x...", max_length=42, required=True)
                    def __init__(self, storage):
                        super().__init__()
                        self._storage = storage
                    async def on_submit(self, i: discord.Interaction):
                        ok = self._storage.remove_wallet(self.addr.value.strip())
                        await i.response.send_message(f"Removed." if ok else "Not found.", ephemeral=True)
                await interaction.response.send_modal(RemoveModal(self._bot.storage))

            @discord.ui.button(label="Copy add", style=discord.ButtonStyle.success, row=2)
            async def btn_copy_add(self, interaction: discord.Interaction, button: discord.ui.Button):
                class CopyAddModal(discord.ui.Modal, title="Copy Add"):
                    addr = discord.ui.TextInput(label="Address", placeholder="0x...", max_length=42, required=True)
                    nick = discord.ui.TextInput(label="Nickname", placeholder="Optional", max_length=32, required=False)
                    async def on_submit(self, i: discord.Interaction):
                        try:
                            from src.copy import add_copy_target, list_copy_targets
                            if not is_valid_eth_address(self.addr.value.strip()):
                                await i.response.send_message("Invalid address.", ephemeral=True)
                                return
                            ok = add_copy_target(self.addr.value.strip(), self.nick.value.strip())
                            t = list_copy_targets()
                            await i.response.send_message(f"Added ({len(t)} targets)." if ok else "Already in list or limit reached.", ephemeral=True)
                        except Exception as e:
                            await i.response.send_message("Failed.", ephemeral=True)
                await interaction.response.send_modal(CopyAddModal())

            @discord.ui.button(label="Copy remove", style=discord.ButtonStyle.danger, row=2)
            async def btn_copy_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
                class CopyRemoveModal(discord.ui.Modal, title="Copy Remove"):
                    addr = discord.ui.TextInput(label="Address", placeholder="0x...", max_length=42, required=True)
                    async def on_submit(self, i: discord.Interaction):
                        try:
                            from src.copy import remove_copy_target, list_copy_targets
                            ok = remove_copy_target(self.addr.value.strip())
                            t = list_copy_targets()
                            await i.response.send_message(f"Removed ({len(t)} left)." if ok else "Not in list.", ephemeral=True)
                        except Exception:
                            await i.response.send_message("Failed.", ephemeral=True)
                await interaction.response.send_modal(CopyRemoveModal())

            @discord.ui.button(label="Copy list", style=discord.ButtonStyle.secondary, row=2)
            async def btn_copy_list(self, interaction: discord.Interaction, button: discord.ui.Button):
                try:
                    from src.copy import list_copy_targets
                    targets = list_copy_targets()
                    if not targets:
                        await interaction.response.send_message("No copy targets.", ephemeral=True)
                    else:
                        msg = "**Copy targets:**\n" + "\n".join(f"• {t.get('nickname', t.get('address','')[:10])}" for t in targets[:15])
                        await interaction.response.send_message(msg[:2000], ephemeral=True)
                except Exception:
                    await interaction.response.send_message("Failed.", ephemeral=True)

            @discord.ui.button(label="Connect Polymarket", style=discord.ButtonStyle.primary, row=3)
            async def btn_conn_pm(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(PolymarketConnectModal(interaction.user.id))

            @discord.ui.button(label="Connect Kalshi", style=discord.ButtonStyle.primary, row=3)
            async def btn_conn_k(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(KalshiConnectModal(interaction.user.id))

            @discord.ui.button(label="Copy kill", style=discord.ButtonStyle.danger, row=4)
            async def btn_copy_kill(self, interaction: discord.Interaction, button: discord.ui.Button):
                try:
                    if hasattr(self._bot.config, "set"):
                        self._bot.config.set("copy_pause", True)
                        if hasattr(self._bot.config, "save"):
                            self._bot.config.save()
                        await interaction.response.send_message("Copy PAUSED (kill switch). Use /copy resume to re-enable.", ephemeral=True)
                    else:
                        await interaction.response.send_message("Config not available.", ephemeral=True)
                except Exception:
                    await interaction.response.send_message("Failed.", ephemeral=True)

            @discord.ui.button(label="Copy settings", style=discord.ButtonStyle.secondary, row=4)
            async def btn_copy_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
                try:
                    cfg = self._bot.config.config if hasattr(self._bot.config, "config") else self._bot.config
                    msg = "**Copy settings:**\n"
                    msg += f"Max order: ${cfg.get('copy_max_order_usd', 100)}\n"
                    msg += f"Size mult: {cfg.get('copy_size_multiplier', 1.0)}\n"
                    msg += f"Throttle: {cfg.get('copy_max_trades_per_minute', 0) or 'off'}/min\n"
                    msg += f"Risk reduction: after {cfg.get('copy_reduce_multiplier_after_trades', 0) or 0} trades -> {cfg.get('copy_reduced_multiplier', 0.5)}x\n"
                    msg += f"Freeze: after {cfg.get('copy_freeze_after_trades', 0) or 0} trades for {cfg.get('copy_freeze_duration_minutes', 60)} min\n"
                    msg += f"Fee: {cfg.get('copy_fee_pct', 0.77)}% | Referral: {cfg.get('copy_referral_discount_pct', 10)}%\n"
                    msg += f"Paused: {cfg.get('copy_pause', False)}"
                    await interaction.response.send_message(msg[:2000], ephemeral=True)
                except Exception:
                    await interaction.response.send_message("Failed.", ephemeral=True)

            @discord.ui.button(label="Top reliable", style=discord.ButtonStyle.success, row=4)
            async def btn_top_reliable(self, interaction: discord.Interaction, button: discord.ui.Button):
                msg = _format_vetted_rankings("reliable", 5)
                await interaction.response.send_message(msg[:2000], ephemeral=True)

            @discord.ui.button(label="Top streak", style=discord.ButtonStyle.success, row=4)
            async def btn_top_streak(self, interaction: discord.Interaction, button: discord.ui.Button):
                msg = _format_vetted_rankings("streak", 5)
                await interaction.response.send_message(msg[:2000], ephemeral=True)

        @self.tree.command(name="menu", description="Show menu with buttons for all options")
        async def menu_slash(interaction: discord.Interaction):
            await interaction.response.send_message("Choose an action:", view=MenuView(self), ephemeral=True)

        # === MESSAGE COMMANDS (fallback) ===
        @self.command(name="menu")
        async def menu_msg(ctx):
            view = MenuView(self)
            await ctx.message.reply("Choose an action:", view=view)

        @self.command(name="ask")
        async def ask_msg(ctx, *, question: str):
            await ctx.message.reply(
                "Chat AI is disabled for performance. Use your external AI agent."
            )

        @self.command(name="ai")
        async def ai_msg(ctx, *, question: str):
            await ctx.message.reply(
                "Chat AI is disabled for performance. Use your external AI agent."
            )

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
                await message.reply("Hi! Use /menu for trading and alert commands.")
                return

            await message.reply(
                "Chat AI is disabled for performance. Use /menu for trading and alerts."
            )
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
