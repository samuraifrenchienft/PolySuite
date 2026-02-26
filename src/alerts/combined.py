"""Combined alert dispatcher for PolySuite - sends to Discord and Telegram simultaneously."""

import hashlib
import logging
import threading
import queue
import time
from typing import Optional

import requests

from src.config import Config

logger = logging.getLogger(__name__)


# Rate limit handling
MIN_INTERVAL_SECONDS = 2.0  # Telegram/Discord rate limits - safer to avoid limits
_last_sent_time = {"discord": 0.0, "telegram": 0.0}
_last_alert_time = 0.0  # Track last alert for heartbeat logic


class CombinedDispatcher:
    """Sends alerts to both Discord and Telegram simultaneously."""

    def __init__(self, config: Optional[Config] = None, backtest_storage=None):
        if config is None:
            config = Config()
        self.config = config
        self.backtest_storage = backtest_storage

        self.has_discord = bool(config.discord_webhook_url)
        self.has_telegram = bool(config.telegram_bot_token and config.telegram_chat_id)

        # Health check channels
        self.telegram_health_chat = config.telegram_chat_id

        # Queue for async sending
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._worker_started = False
        self._start_worker()

    def _start_worker(self):
        """Start background worker for sending alerts."""
        if self._worker_started:
            return
        thread = threading.Thread(
            target=self._worker, daemon=True, name="alert-dispatcher"
        )
        thread.start()
        self._worker_started = True

    def mark_alert_sent(self):
        """Mark that an alert was sent (for heartbeat logic)."""
        global _last_alert_time
        _last_alert_time = time.time()

    def get_last_alert_time(self) -> float:
        """Get timestamp of last alert sent."""
        global _last_alert_time
        return _last_alert_time

    def _log_alert(self, alert_type: str, data: tuple):
        """Log alert to backtest storage for performance tracking."""
        if not self.backtest_storage:
            return
        try:
            market_id = ""
            if alert_type == "convergence" and len(data) >= 4:
                market_id = str((data[3] or {}).get("market_id", ""))
            elif alert_type == "arb" and data:
                market_id = str((data[0] or {}).get("market_id") or (data[0] or {}).get("condition_id", ""))
            elif alert_type in ("new_market", "volume_spike", "market_resolved") and data:
                market_id = str((data[0] or {}).get("id") or (data[0] or {}).get("conditionId", ""))
            elif alert_type == "whale_batch" and data and data[0]:
                market_id = str((data[0][0] or {}).get("market_id", "")) if data[0] else ""
            content_hash = str(hash(str(data)))[:64]
            self.backtest_storage.log_alert(alert_type, content_hash, market_id)
        except Exception:
            pass

    def _worker(self):
        """Background worker that processes alert queue."""
        while True:
            try:
                alert_type, data = self._queue.get(timeout=1)
                if alert_type == "convergence":
                    self._send_convergence(*data)
                elif alert_type == "arb":
                    self._send_arb(*data)
                elif alert_type == "new_market":
                    self._send_new_market(*data)
                elif alert_type == "health":
                    self._send_health(*data)
                elif alert_type == "volume_spike":
                    self._send_volume_spike(*data)
                elif alert_type == "market_resolved":
                    self._send_market_resolved(*data)
                elif alert_type == "wallet_update":
                    self._send_wallet_update(*data)
                elif alert_type == "smart_money":
                    self._send_smart_money(*data)
                elif alert_type == "whale_batch":
                    self._send_whale_batch(*data)
                self._log_alert(alert_type, data)
                self.mark_alert_sent()
            except queue.Empty:
                continue
            except Exception as e:
                logger.warning("[AlertWorker] Error: %s", type(e).__name__)

    def _wait_for_rate_limit(self, channel: str):
        """Wait to respect rate limits."""
        now = time.monotonic()
        wait = MIN_INTERVAL_SECONDS - (now - _last_sent_time[channel])
        if wait > 0:
            time.sleep(wait)
        _last_sent_time[channel] = time.monotonic()

    def _send_discord(self, message: str) -> bool:
        """Send to Discord."""
        if not self.has_discord:
            return False
        try:
            self._wait_for_rate_limit("discord")
            url = self.config.discord_webhook_url
            resp = requests.post(url, json={"content": message}, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            print(f"[Discord] Error: {e}")
            return False

    def _send_discord_webhook(self, payload: dict, url: Optional[str] = None) -> bool:
        """Send full webhook payload to Discord (e.g. embeds). Optional url override."""
        target = url or self.config.discord_webhook_url
        if not target:
            return False
        try:
            self._wait_for_rate_limit("discord")
            resp = requests.post(target, json=payload, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning("[Discord] Error: %s", type(e).__name__)
            return False

    # Discord embed colors per alert type (left edge bar)
    EMBED_COLORS = {
        "crypto": 0x3498DB,   # Blue
        "sports": 0x2ECC71,   # Green
        "politics": 0x9B59B6, # Purple
        "arb": 0xF1C40F,     # Gold
        "convergence": 0xE67E22,  # Orange
        "whale": 0xE67E22,   # Orange
        "kalshi": 0x1ABC9C,  # Teal
        "jupiter": 0x9B59B6, # Purple (Jupiter brand)
        "default": 0x5865F2,  # Discord blurple
    }

    def _send_telegram(self, message: str, chat_id: Optional[str] = None) -> bool:
        """Send to Telegram."""
        if not self.has_telegram:
            return False
        try:
            self._wait_for_rate_limit("telegram")
            token = self.config.telegram_bot_token
            target = chat_id or self.config.telegram_chat_id
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(
                url, json={"chat_id": target, "text": message}, timeout=10
            )
            return resp.status_code == 200
        except Exception as e:
            print(f"[Telegram] Error: {e}")
            return False

    def _get_market_link(self, market_id_or_obj) -> str:
        """Get Polymarket link. Prefer slug when obj has it (dict with slug/conditionId/id)."""
        if isinstance(market_id_or_obj, dict):
            from src.alerts.formatter import _polymarket_link
            return _polymarket_link(market_id_or_obj) or f"https://polymarket.com/market/{market_id_or_obj.get('id') or market_id_or_obj.get('conditionId') or ''}"
        return f"https://polymarket.com/market/{market_id_or_obj}"

    def _send_convergence(
        self, market: dict, wallets: list, threshold: float, convergence: dict
    ):
        """Send convergence alert to all channels."""
        market_id = market.get("id") or market.get("conditionId") or ""

        # Convert has_early_entry to boolean safely
        try:
            has_early = bool(convergence.get("has_early_entry"))
        except Exception:
            has_early = False

        # Determine urgency
        urgency = (
            "CRITICAL"
            if has_early and len(wallets) >= 3
            else ("HIGH" if has_early or len(wallets) >= 3 else "NORMAL")
        )

        emoji = "🔴" if urgency == "CRITICAL" else ("🟠" if urgency == "HIGH" else "🔵")

        # Clean title
        lines = [
            f"{emoji} CONVERGENCE {urgency}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"👥 **{len(wallets)}** expert traders | 🎯 **{threshold}%+** win rate",
        ]

        if has_early:
            lines.append("🚀 Early entry detected!")

        lines.append("")
        lines.append("📊 *Top Traders:*")

        for w in wallets[:5]:  # Top 5 wallets
            early_flag = " 🚀" if convergence and w.get("is_early_entry") else ""
            wr = w.get("win_rate", 0)
            wins = w.get("wins", 0)
            trades = w.get("total_trades", 0)
            lines.append(
                f"• {w.get('nickname', 'Unknown')}: **{wr:.1f}%** ({wins}/{trades}){early_flag}"
            )

        lines.extend(["", f"📈 **{market.get('question', 'Unknown')[:180]}**"])

        volume = market.get("volume", 0)
        if volume:
            lines.append(f"💵 Volume: **${volume:,.0f}**")

        # Add link to market (use full market for slug when available)
        link = self._get_market_link(market) if market_id else ""
        if link:
            lines.append(f"[Trade →]({link})")

        msg = "\n".join(lines)

        # Discord: colored embed (orange for convergence)
        webhook = (
            getattr(self.config, "discord_alerts_webhook_url", None)
            or self.config.discord_webhook_url
        )
        if webhook:
            payload = {
                "embeds": [{
                    "title": f"👥 Convergence {urgency}",
                    "description": msg,
                    "color": self.EMBED_COLORS["convergence"],
                    "url": self._get_market_link(market) if market_id else None,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }]
            }
            t1 = threading.Thread(
                target=lambda: self._send_discord_webhook(payload, url=webhook)
            )
        else:
            t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _send_arb(self, arb: dict):
        """Send arbitrage alert to all channels. Discord: gold embed edge."""
        market_id = arb.get("market_id") or arb.get("condition_id") or ""

        yes_ask = arb.get("yes_ask", arb.get("yes_price", 0))
        no_ask = arb.get("no_ask", arb.get("no_price", 0))
        spread = abs((yes_ask + no_ask) - 1.0) * 100 if yes_ask and no_ask else 0

        try:
            profit = float(arb.get("profit_pct", 0))
        except (ValueError, TypeError):
            profit = 0

        # Color coding based on profit
        if profit >= 2.0:
            emoji = "🟢"
        elif profit >= 1.0:
            emoji = "🔵"
        else:
            emoji = "🟠"

        lines = [
            f"{emoji} ARBITRAGE: **{profit:.2f}%**",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"YES: **${yes_ask:.2f}** | NO: **${no_ask:.2f}**",
            f"Spread: {spread:.2f}% | Total: ${arb.get('total', 0):,.0f}",
            "",
            f"📈 **{arb.get('question', 'Unknown')[:180]}**",
        ]

        volume = arb.get("volume", 0)
        if volume:
            lines.append(f"💵 Volume: **${volume:,.0f}**")

        # Add link
        if market_id:
            lines.append(f"[Trade →]({self._get_market_link(market_id)})")

        msg = "\n".join(lines)

        # Discord: colored embed (gold for arb)
        webhook = (
            getattr(self.config, "discord_alerts_webhook_url", None)
            or self.config.discord_webhook_url
        )
        if webhook:
            payload = {
                "embeds": [{
                    "title": "💰 Arbitrage",
                    "description": msg,
                    "color": self.EMBED_COLORS["arb"],
                    "url": self._get_market_link(market_id) if market_id else None,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }]
            }
            t1 = threading.Thread(
                target=lambda: self._send_discord_webhook(payload, url=webhook)
            )
        else:
            t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _send_new_market(self, market: dict):
        """Send new market alert to all channels."""
        market_id = market.get("id") or market.get("conditionId") or ""

        # Get timeframe info
        end_date = market.get("endDate") or market.get("end_date") or ""
        start_date = market.get("startDate") or market.get("start_date") or ""

        lines = [
            "🆕 NEW MARKET",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📈 **{market.get('question', 'Unknown')[:180]}**",
            "",
        ]

        volume = market.get("volume", 0)
        liquidity = market.get("liquidity", 0)

        if volume or liquidity:
            parts = []
            if volume:
                parts.append(f"💵 Vol: ${volume:,.0f}")
            if liquidity:
                parts.append(f"💧 Liq: ${liquidity:,.0f}")
            lines.append(" | ".join(parts))

        # Add timeframe info
        if end_date:
            lines.append(
                f"⏰ Ends: {end_date[:10] if len(end_date) > 10 else end_date}"
            )

        # Add category if available
        category = market.get("category") or market.get("groupItemTitle")
        if category:
            lines.append(f"🏷️ {category}")

        # Add link
        if market_id:
            lines.append(f"[Trade →]({self._get_market_link(market_id)})")

        msg = "\n".join(lines)

        t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _send_volume_spike(self, market: dict, multiplier: float):
        """Send volume spike alert."""
        market_id = market.get("id") or market.get("conditionId") or ""

        lines = [
            "📈 VOLUME SPIKE",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📈 **{market.get('question', 'Unknown')[:180]}**",
            "",
            f"⚡ **{multiplier:.1f}x** normal volume",
        ]

        volume = market.get("volume", 0)
        if volume:
            lines.append(f"💵 Volume: **${volume:,.0f}**")

        avg_volume = market.get("avg_volume", volume / multiplier) if multiplier else 0
        if avg_volume:
            lines.append(f"📊 Avg: **${avg_volume:,.0f}**")

        # Add link
        if market_id:
            lines.append(f"[View →]({self._get_market_link(market_id)})")

        msg = "\n".join(lines)

        t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _send_market_resolved(self, market: dict, outcome: str):
        """Send market resolution alert."""
        market_id = market.get("id") or market.get("conditionId") or ""

        lines = [
            "🎯 MARKET RESOLVED",
            "",
            f"**{market.get('question', 'Unknown')[:250]}**",
            "",
            f"**Outcome:** {outcome}",
        ]

        volume = market.get("volume", 0)
        if volume:
            lines.append(f"**Total Volume:** ${volume:,.0f}")

        # Add link
        if market_id:
            lines.append(f"[View on Polymarket]({self._get_market_link(market_id)})")

        msg = "\n".join(lines)

        t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _send_wallet_update(self, wallet: dict, position_change: dict):
        """Send wallet position update alert."""
        lines = [
            "👤 WALLET UPDATE",
            "",
            f"**{wallet.get('nickname', wallet.get('address', 'Unknown')[:20])}**",
            "",
        ]

        if position_change.get("new_position"):
            lines.append(
                f"**New Position:** {position_change.get('side', '?').upper()} ${position_change.get('size', 0):,.0f}"
            )
            lines.append(f"**Entry:** ${position_change.get('entry_price', 0):.2f}")

        if position_change.get("closed"):
            lines.append(
                f"**Position Closed** - P/L: {position_change.get('pnl', 0):.2f}%"
            )

        market = position_change.get("market", {})
        if market:
            lines.append(f"**Market:** {market.get('question', 'Unknown')[:100]}")
            market_id = market.get("id") or market.get("conditionId")
            if market_id:
                lines.append(
                    f"[View on Polymarket]({self._get_market_link(market_id)})"
                )

        msg = "\n".join(lines)

        t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def send_whale_batch(self, trades: list):
        """Queue batched whale trades for sending."""
        self._queue.put(("whale_batch", (trades,)))

    def _send_whale_batch(self, trades: list):
        """Send batched whale trades as one consolidated alert."""
        if not trades:
            return

        # Group by wallet
        by_wallet = {}
        for t in trades:
            wallet = t.get("wallet", "Unknown")
            if wallet not in by_wallet:
                by_wallet[wallet] = []
            by_wallet[wallet].append(t)

        # Build embed - color per type
        embed = {
            "title": "🐋 Whale Activity",
            "description": f"**{len(trades)} new trades detected from {len(by_wallet)} wallet(s)**",
            "color": 0xE67E22,
            "fields": [],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "footer": {"text": "PolySuite • " + time.strftime("%H:%M UTC", time.gmtime())},
        }

        for wallet, wallet_trades in by_wallet.items():
            total_size = sum(t.get("size", 0) for t in wallet_trades)
            trade_details = "\n".join(
                [
                    f"  {t.get('side', '?').upper()}: ${t.get('size', 0):,.0f} → {t.get('question', '?')[:25]}..."
                    for t in wallet_trades[:3]
                ]
            )
            if len(wallet_trades) > 3:
                trade_details += f"\n  ... +{len(wallet_trades) - 3} more"

            embed["fields"].append(
                {
                    "name": f"{wallet} (${total_size:,.0f} total)",
                    "value": trade_details,
                    "inline": False,
                }
            )

        # Send to Discord
        if self.has_discord:
            self._wait_for_rate_limit("discord")
            try:
                requests.post(
                    self.config.discord_webhook_url,
                    json={"embeds": [embed]},
                    timeout=10,
                )
            except Exception as e:
                logger.warning("[WhaleBatch] Discord error: %s", type(e).__name__)

        # Send to Telegram
        if self.has_telegram and self.telegram_health_chat:
            msg = f"🐋 *Whale Alert*\n\n{len(trades)} trades from {len(by_wallet)} wallet(s)\n\n"
            for wallet, wallet_trades in by_wallet.items():
                total = sum(t.get("size", 0) for t in wallet_trades)
                top_trades = "\n".join(
                    [
                        f"  {t.get('side', '?').upper()}: ${t.get('size', 0):,.0f} → {t.get('question', '?')[:30]}"
                        for t in wallet_trades[:2]
                    ]
                )
                if len(wallet_trades) > 2:
                    top_trades += f"\n  ... +{len(wallet_trades) - 2} more"
                msg += f"*{wallet}* (${total:,.0f}):\n{top_trades}\n\n"

            self._send_telegram(msg, self.telegram_health_chat)

    def _send_health(self, message: str):
        """Send health check - Discord + Telegram private."""
        t1 = threading.Thread(target=self._send_discord, args=(message,))
        t2 = threading.Thread(
            target=self._send_telegram, args=(message, self.telegram_health_chat)
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def send_to_alerts(self, message: str, category: Optional[str] = None, backtest_meta: Optional[dict] = None):
        """Send to alerts channel. Use channel_overrides when category has a dedicated channel.
        Discord: uses colored embed when category is provided (crypto=blue, sports=green, politics=purple).
        backtest_meta: optional {alert_type, market_id} for alert_log."""
        overrides = getattr(self.config, "channel_overrides", {}) or {}
        override = overrides.get(category, {}) if category else {}

        chat = (
            override.get("telegram_chat_id")
            or getattr(self.config, "telegram_alerts_chat_id", None)
            or self.telegram_health_chat
        )
        webhook = (
            override.get("discord_webhook_url")
            or getattr(self.config, "discord_alerts_webhook_url", None)
            or self.config.discord_webhook_url
        )

        if webhook:
            try:
                self._wait_for_rate_limit("discord")
                color = self.EMBED_COLORS.get(category, self.EMBED_COLORS["default"])
                payload = {
                    "embeds": [{
                        "description": message,
                        "color": color,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }]
                }
                self._send_discord_webhook(payload, url=webhook)
            except Exception as e:
                print(f"[Alerts-Discord] Error: {e}")

        if chat:
            self._send_telegram(message, chat)

        if self.backtest_storage and backtest_meta:
            self.backtest_storage.log_alert(
                alert_type=backtest_meta.get("alert_type", "unknown"),
                content_hash=hashlib.sha256(message.encode()).hexdigest(),
                market_id=backtest_meta.get("market_id"),
            )

    def send_to_trends(self, message: str):
        """Send to trends channel (pump.fun, crypto moves)."""
        chat = (
            getattr(self.config, "telegram_trends_chat_id", None)
            or self.telegram_health_chat
        )
        webhook = (
            getattr(self.config, "discord_trends_webhook_url", None)
            or self.config.discord_webhook_url
        )

        if webhook:
            try:
                requests.post(webhook, json={"content": message}, timeout=10)
            except Exception as e:
                logger.warning("[Trends-Discord] Error: %s", type(e).__name__)

        if chat:
            self._send_telegram(message, chat)

    def _send_smart_money(self, wallets: list):
        """Send smart money wallet alert."""
        from src.alerts import AlertDispatcher

        # Format using AlertDispatcher
        dispatcher = AlertDispatcher(self.config.discord_webhook_url)
        payload = dispatcher.format_smart_money_alert(wallets)

        # Send rich embed to Discord via webhook payload
        t1 = threading.Thread(target=self._send_discord_webhook, args=(payload,))
        t2 = threading.Thread(
            target=self._send_telegram,
            args=(
                f"🧠 Smart Money: {len(wallets)} new wallets detected",
                self.telegram_health_chat,
            ),
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # Public methods - queue for async sending
    def send_convergence(
        self, market: dict, wallets: list, threshold: float, convergence: dict
    ):
        self._queue.put(("convergence", (market, wallets, threshold, convergence)))

    def send_arb(self, arb: dict):
        self._queue.put(("arb", (arb,)))

    def send_new_market(self, market: dict):
        self._queue.put(("new_market", (market,)))

    def send_health(self, message: str):
        self._queue.put(("health", (message,)))

    def send_volume_spike(self, market: dict, multiplier: float):
        self._queue.put(("volume_spike", (market, multiplier)))

    def send_market_resolved(self, market: dict, outcome: str):
        self._queue.put(("market_resolved", (market, outcome)))

    def send_wallet_update(self, wallet: dict, position_change: dict):
        self._queue.put(("wallet_update", (wallet, position_change)))

    def send_smart_money_alert(self, wallets: list):
        """Send smart money wallet alert."""
        self._queue.put(("smart_money", (wallets,)))
