"""Combined alert dispatcher for PolySuite - sends to Discord and Telegram simultaneously."""

import threading
import queue
import time
from typing import Optional

import requests

from src.config import Config


# Rate limit handling
MIN_INTERVAL_SECONDS = 1.0  # Telegram/Discord rate limits
_last_sent_time = {"discord": 0.0, "telegram": 0.0}


class CombinedDispatcher:
    """Sends alerts to both Discord and Telegram simultaneously."""

    def __init__(self, config: Optional[Config] = None):
        if config is None:
            config = Config()
        self.config = config

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
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[AlertWorker] Error: {e}")

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

    def _get_market_link(self, market_id: str) -> str:
        """Get Polymarket link for a market."""
        return f"https://polymarket.com/market/{market_id}"

    def _send_convergence(
        self, market: dict, wallets: list, threshold: float, convergence: dict
    ):
        """Send convergence alert to all channels."""
        market_id = market.get("id") or market.get("conditionId") or ""

        # Convert has_early_entry to boolean safely
        try:
            has_early = bool(convergence.get("has_early_entry"))
        except:
            has_early = False

        # Format message with full details
        urgency = (
            "CRITICAL"
            if has_early and len(wallets) >= 3
            else ("HIGH" if has_early or len(wallets) >= 3 else "NORMAL")
        )

        lines = [
            f"🔥 CONVERGENCE ALERT - {urgency}",
            "",
            f"**Traders:** {len(wallets)} high-performers ({threshold}%+ win rate)",
            f"**Early Entry:** {'Yes' if convergence.get('has_early_entry') else 'No'}",
            "",
            "*Top Wallets:*",
        ]
        for w in wallets[:5]:  # Top 5 wallets
            lines.append(
                f"• {w.get('nickname', 'Unknown')}: {w.get('win_rate', 0):.1f}% ({w.get('wins', 0)}/{w.get('total_trades', 0)})"
            )

        lines.extend(["", f"**Market:** {market.get('question', 'Unknown')[:200]}"])

        volume = market.get("volume", 0)
        if volume:
            lines.append(f"**Volume:** ${volume:,.0f}")

        # Add link to market
        if market_id:
            lines.append(f"[View on Polymarket]({self._get_market_link(market_id)})")

        msg = "\n".join(lines)

        # Send to both simultaneously
        t1 = threading.Thread(target=self._send_discord, args=(msg,))
        t2 = threading.Thread(target=self._send_telegram, args=(msg,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _send_arb(self, arb: dict):
        """Send arbitrage alert to all channels."""
        market_id = arb.get("market_id") or arb.get("condition_id") or ""

        yes_ask = arb.get("yes_ask", arb.get("yes_price", 0))
        no_ask = arb.get("no_ask", arb.get("no_price", 0))
        spread = abs((yes_ask + no_ask) - 1.0) * 100 if yes_ask and no_ask else 0

        try:
            profit = float(arb.get("profit_pct", 0))
        except (ValueError, TypeError):
            profit = 0

        lines = [
            "💰 ARBITRAGE OPPORTUNITY",
            "",
            f"**Profit:** {profit:.2f}%",
            f"**Yes Price:** ${yes_ask:.2f}",
            f"**No Price:** ${no_ask:.2f}",
            f"**Spread:** {spread:.2f}%",
            "",
            f"**Total:** ${arb.get('total', 0):,.0f}",
            "",
            f"**Market:** {arb.get('question', 'Unknown')[:200]}",
        ]

        volume = arb.get("volume", 0)
        if volume:
            lines.append(f"**Volume:** ${volume:,.0f}")

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

    def _send_new_market(self, market: dict):
        """Send new market alert to all channels."""
        market_id = market.get("id") or market.get("conditionId") or ""

        # Get timeframe info
        end_date = market.get("endDate") or market.get("end_date") or ""
        start_date = market.get("startDate") or market.get("start_date") or ""

        lines = [
            "🆕 NEW MARKET",
            "",
            f"**{market.get('question', 'Unknown')[:300]}**",
            "",
        ]

        volume = market.get("volume", 0)
        if volume:
            lines.append(f"**Volume:** ${volume:,.0f}")

        liquidity = market.get("liquidity", 0)
        if liquidity:
            lines.append(f"**Liquidity:** ${liquidity:,.0f}")

        # Add timeframe info
        if end_date:
            lines.append(f"**Ends:** {end_date}")
        if start_date:
            lines.append(f"**Starts:** {start_date}")

        # Add category if available
        category = market.get("category") or market.get("groupItemTitle")
        if category:
            lines.append(f"**Category:** {category}")

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

    def _send_volume_spike(self, market: dict, multiplier: float):
        """Send volume spike alert."""
        market_id = market.get("id") or market.get("conditionId") or ""

        lines = [
            "📈 VOLUME SPIKE",
            "",
            f"**{market.get('question', 'Unknown')[:250]}**",
            "",
            f"**Spike:** {multiplier:.1f}x normal volume",
        ]

        volume = market.get("volume", 0)
        if volume:
            lines.append(f"**Volume:** ${volume:,.0f}")

        avg_volume = market.get("avg_volume", volume / multiplier) if multiplier else 0
        if avg_volume:
            lines.append(f"**Avg Volume:** ${avg_volume:,.0f}")

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

    def _send_smart_money(self, wallets: list):
        """Send smart money wallet alert."""
        from src.alerts import AlertDispatcher

        # Format using AlertDispatcher
        dispatcher = AlertDispatcher(self.config.discord_webhook_url)
        payload = dispatcher.format_smart_money_alert(wallets)

        # Send rich embed to Discord
        t1 = threading.Thread(target=self._send_discord, args=(payload,))
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
