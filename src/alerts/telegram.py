"""Telegram alert dispatcher for PolySuite."""

import requests
from typing import List, Dict, Optional


class TelegramDispatcher:
    """Dispatches alerts to Telegram."""

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        """Initialize with Telegram bot credentials.

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Telegram chat ID (user or group)
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self._chart = None

    def _get_chart(self):
        """Get chart client (lazy load)."""
        if self._chart is None:
            from src.market.quickchart import QuickChartClient
            from src.config import Config

            config = Config()
            self._chart = QuickChartClient(config.quickchart_api_key)
        return self._chart

    def is_configured(self) -> bool:
        """Check if Telegram is configured."""
        return bool(self.bot_token and self.chat_id)

    def send_photo(self, photo_url: str, caption: str = "") -> bool:
        """Send photo to Telegram.

        Args:
            photo_url: URL of the image
            caption: Optional caption

        Returns:
            True if successful
        """
        if not self.is_configured():
            return False

        try:
            url = f"{self.api_url}/sendPhoto"
            data = {
                "chat_id": self.chat_id,
                "photo": photo_url,
                "parse_mode": "Markdown",
            }
            if caption:
                data["caption"] = caption
            resp = requests.post(url, data=data, timeout=30)
            return resp.status_code == 200
        except requests.RequestException as e:
            print(f"Telegram photo error: {e}")
            return False

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send message to Telegram.

        Args:
            text: Message text
            parse_mode: Parse mode (Markdown or HTML)

        Returns:
            True if successful
        """
        if not self.is_configured():
            print("Telegram not configured")
            return False

        url = f"{self.api_url}/sendMessage"
        data = {"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode}

        try:
            resp = requests.post(url, json=data, timeout=30)
            return resp.status_code == 200
        except requests.RequestException as e:
            print(f"Telegram send error: {e}")
            return False

    def format_convergence_alert(
        self, market: Dict, wallets: List[Dict], threshold: float
    ) -> str:
        """Format convergence alert for Telegram."""
        lines = [
            "🔥 *CONVERGENCE ALERT*",
            "",
            f"*Traders:* {len(wallets)} high-performers",
            f"*Threshold:* {threshold}%+",
            "",
            "*Wallets:*",
        ]

        for w in wallets:
            lines.append(
                f"• {w['nickname']}: {w['win_rate']:.1f}% ({w['wins']}/{w['total_trades']})"
            )

        lines.extend(["", "*Market:*"])
        lines.append(market.get("question", "Unknown")[:200])

        volume = market.get("volume", 0)
        if isinstance(volume, (int, float)):
            lines.append(f"*Volume:* ${volume:,.0f}")

        market_id = market.get("id") or market.get("conditionId")
        if market_id:
            lines.append(
                f"[View on Polymarket](https://polymarket.com/market/{market_id})"
            )

        return "\n".join(lines)

    def format_new_market_alert(self, market: Dict) -> str:
        """Format new market alert for Telegram."""
        volume = float(market.get("volume", 0) or 0)
        vol_emoji = "🟢" if volume >= 100000 else ("🟡" if volume >= 10000 else "🔴")
        vol_label = (
            "High" if volume >= 100000 else ("Medium" if volume >= 10000 else "Low")
        )

        # Get current odds
        outcome_prices = market.get("outcomePrices", [])
        odds_text = "N/A"
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                yes_odds = float(outcome_prices[0])
                no_odds = float(outcome_prices[1])
                odds_text = f"YES {yes_odds * 100:.0f}% | NO {no_odds * 100:.0f}%"
            except:
                pass

        lines = [
            "🆕 *NEW MARKET*",
            "",
            market.get("question", "Unknown")[:300],
            "",
            f"*Odds:* {odds_text}",
            f"*Volume:* {vol_emoji} {vol_label}",
        ]

        market_id = market.get("id") or market.get("conditionId")
        if market_id:
            lines.append(
                f"[View on Polymarket](https://polymarket.com/market/{market_id})"
            )

        return "\n".join(lines)

    def format_arb_alert(self, arb: Dict) -> str:
        """Format arbitrage alert for Telegram."""
        profit = arb.get("profit_pct", 0)
        volume = float(arb.get("volume", 0) or 0)
        vol_emoji = "🟢" if volume >= 100000 else ("🟡" if volume >= 10000 else "🔴")
        vol_label = (
            "High" if volume >= 100000 else ("Medium" if volume >= 10000 else "Low")
        )

        lines = [
            f"💰 *ARBITRAGE: {profit:.1f}%*",
            "",
            f"*YES:* {arb.get('yes_price', 0):.2f} | *NO:* {arb.get('no_price', 0):.2f}",
            f"*Volume:* {vol_emoji} {vol_label}",
            f"*⚠️* Check fees before trading",
            "",
            arb.get("question", "Unknown")[:200],
        ]

        market_id = arb.get("market_id") or arb.get("condition_id")
        if market_id:
            lines.append(
                f"[View on Polymarket](https://polymarket.com/market/{market_id})"
            )

        return "\n".join(lines)

    def send_arb_alert(self, arb: Dict) -> bool:
        """Send arbitrage alert."""
        text = self.format_arb_alert(arb)
        return self.send_message(text)

    def send_convergence_alert(
        self, market: Dict, wallets: List[Dict], threshold: float
    ) -> bool:
        """Send convergence alert with chart."""
        text = self.format_convergence_alert(market, wallets, threshold)

        # Send alert with chart
        try:
            chart = self._get_chart()
            market_name = market.get("question", "Unknown")
            chart_url = chart.convergence_chart(market_name, wallets)

            # Send chart first, then text
            self.send_photo(chart_url, caption=text[:1024])
        except Exception as e:
            # Fallback to text only
            print(f"Chart error: {e}")

        return self.send_message(text)

    def send_new_market_alert(self, market: Dict) -> bool:
        """Send new market alert."""
        text = self.format_new_market_alert(market)
        return self.send_message(text)

    def test_connection(self) -> bool:
        """Test Telegram connection."""
        if not self.is_configured():
            return False

        url = f"{self.api_url}/getMe"
        try:
            resp = requests.get(url, timeout=30)
            return resp.status_code == 200
        except requests.RequestException as e:
            print(f"Telegram connection test error: {e}")
