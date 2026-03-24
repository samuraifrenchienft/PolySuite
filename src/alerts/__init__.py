"""Enhanced alert dispatcher for PolySuite with clear buy signals."""

import json
import logging
import time
from typing import List, Dict, Optional, Set
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

COLORS = {
    "CRITICAL": 0xEF4444,  # Red - strong buy
    "HIGH": 0xF97316,  # Orange - buy
    "NORMAL": 0x3B82F6,  # Blue - info
    "EARLY": 0x22C55E,  # Green - early entry
}


def get_volume_emoji(volume: float) -> str:
    """Get emoji for volume level."""
    if volume >= 100000:
        return "🟢"  # High
    elif volume >= 10000:
        return "🟡"  # Medium
    else:
        return "🔴"  # Low


def get_volume_label(volume: float) -> str:
    """Get label for volume level."""
    if volume >= 100000:
        return "High"
    elif volume >= 10000:
        return "Medium"
    else:
        return "Low"


class AlertDispatcher:
    """Dispatches actionable alerts to Discord with clear buy signals."""

    def __init__(self, webhook_url: str = "", cooldown_seconds: int = 300):
        self.webhook_url = webhook_url
        self.cooldown_seconds = cooldown_seconds
        self._last_alerts: Dict[str, float] = {}
        self._last_alerts_max = 1000  # Evict oldest when exceeded

    def _prune_alerts_if_needed(self):
        """Keep _last_alerts bounded to avoid unbounded growth."""
        if len(self._last_alerts) > self._last_alerts_max:
            sorted_keys = sorted(
                self._last_alerts.keys(),
                key=lambda k: self._last_alerts[k],
            )
            for k in sorted_keys[: len(sorted_keys) - self._last_alerts_max]:
                del self._last_alerts[k]

    def is_on_cooldown(self, market_id: str) -> bool:
        if market_id not in self._last_alerts:
            return False
        elapsed = time.time() - self._last_alerts[market_id]
        return elapsed < self.cooldown_seconds

    def set_cooldown(self, market_id: str):
        self._last_alerts[market_id] = time.time()
        self._prune_alerts_if_needed()

    def set_cooldown_seconds(self, seconds: int):
        self.cooldown_seconds = seconds

    def send_webhook(self, payload: Dict) -> bool:
        if not self.webhook_url:
            logger.debug("No webhook URL configured")
            return False
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code not in (204, 200):
                logger.warning(
                    "Webhook failed: %s - %s", resp.status_code, resp.text[:200]
                )
                return False
            return True
        except requests.RequestException as e:
            logger.warning("Failed to send webhook: %s", e)
            return False

    def _determine_urgency(self, convergence: Dict) -> str:
        """Determine alert urgency based on convergence strength."""
        wallet_count = len(convergence.get("wallets", []))
        has_early = convergence.get("has_early_entry", False)

        if wallet_count >= 3 and has_early:
            return "CRITICAL"
        elif wallet_count >= 3 or has_early:
            return "HIGH"
        elif wallet_count >= 2:
            return "NORMAL"
        return "NORMAL"

    def _get_consensus_direction(
        self, wallets: List[Dict], positions: List[Dict]
    ) -> str:
        """Determine consensus direction from wallet positions."""
        yes_votes = 0
        no_votes = 0

        for pos in positions:
            side = pos.get("side", "").upper()
            if side == "BUY":
                yes_votes += 1
            elif side == "SELL":
                no_votes += 1

        if yes_votes > no_votes:
            return "YES"
        elif no_votes > yes_votes:
            return "NO"
        return "BUY YES"

    def format_convergence_alert(
        self,
        market: Dict,
        wallets: List[Dict],
        threshold: float,
        convergence: Dict = None,
        positions: List[Dict] = None,
    ) -> Dict:
        """Format alert with clear buy signal."""
        market_id = market.get("id") or market.get("conditionId", "unknown")

        urgency = "NORMAL"
        if convergence:
            urgency = self._determine_urgency(convergence)

        direction = self._get_consensus_direction(wallets, positions or [])

        emoji = "🔴" if urgency == "CRITICAL" else ("🟠" if urgency == "HIGH" else "🔵")
        signal = (
            f"{emoji} **{direction} SIGNAL**"
            if direction != "BUY YES"
            else f"🔵 **CONVERGENCE**"
        )

        title = f"{signal}"

        description = f"**{len(wallets)}** expert traders converging\n"
        description += f"Threshold: **{threshold}%**+ win rate\n\n"

        for w in wallets:
            early = " 🚀" if convergence and w.get("is_early_entry") else ""
            description += f"• **{w['nickname']}** — {w['win_rate']:.1f}%{early}\n"

        volume = market.get("volume", 0)
        volume_str = (
            f"${volume:,.0f}" if isinstance(volume, (int, float)) else str(volume)
        )

        fields = [
            {
                "name": "📊 Market",
                "value": market.get("question", "Unknown")[:200],
                "inline": False,
            },
            {"name": "💵 Volume", "value": volume_str, "inline": True},
            {"name": "👥 Traders", "value": str(len(wallets)), "inline": True},
            {"name": "🎯 Direction", "value": direction, "inline": True},
        ]

        if convergence and convergence.get("market_age_hours"):
            age = convergence["market_age_hours"]
            fields.append({"name": "⏱️ Age", "value": f"{age:.1f}h old", "inline": True})

        if convergence and convergence.get("early_entry_wallets"):
            fields.append(
                {
                    "name": "🚀 Early Entrants",
                    "value": ", ".join(convergence["early_entry_wallets"][:3]),
                    "inline": False,
                }
            )

        embed = {
            "title": title,
            "description": description,
            "color": COLORS.get(urgency, COLORS["NORMAL"]),
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": f"Urgency: {urgency}"},
        }

        if market_id and market_id != "unknown":
            embed["url"] = f"https://polymarket.com/market/{market_id}"

        return {"embeds": [embed]}

    def format_smart_money_alert(self, wallets: List[Dict]) -> Dict:
        """Format alert for new smart money wallets."""
        embed = {
            "title": "🧠 Smart Money Detected",
            "description": f"**{len(wallets)} new high-performing wallet(s) added to tracking**",
            "color": COLORS["HIGH"],
            "fields": [],
            "timestamp": datetime.utcnow().isoformat(),
            "url": "https://polymarket.com/leaderboard",
        }

        for w in wallets:
            nickname = w.get("nickname", "Unknown")
            addr = w.get("address", "Unknown")
            addr_short = addr[:10] if len(addr) > 10 else addr
            addr_link = addr[:42] if len(addr) > 42 else addr  # Full address for link
            win_rate = w.get("win_rate", 0)
            trades = w.get("total_trades", 0)
            wins = w.get("wins", 0)
            volume = w.get("trade_volume", 0)
            profit = w.get("profit", 0)

            # Color code win rate
            if win_rate >= 65:
                wr_emoji = "🟢"
            elif win_rate >= 55:
                wr_emoji = "🟡"
            else:
                wr_emoji = "🔴"

            # Best category if available
            best_cat = w.get("best_category", "N/A")

            field = {
                "name": f"{nickname} (`{addr_short}...`)",
                "value": (
                    f"{wr_emoji} **{win_rate:.1f}%** | 📊 **{wins}/{trades}** trades | 💵 **${volume:,.0f}**\n"
                    f"💰 Profit: **${profit:,.0f}** | 🎯 Best: {best_cat}\n"
                    f"[View on Polymarket](https://polymarket.com/profile/{addr_link})"
                ),
                "inline": False,
            }
            embed["fields"].append(field)

        return {"embeds": [embed]}

    def format_new_market_alert(self, market: Dict, category: str = None) -> Dict:
        """Format new market alert."""
        volume = float(market.get("volume", 0) or 0)
        vol_emoji = get_volume_emoji(volume)
        vol_label = get_volume_label(volume)

        # Get current odds
        outcome_prices = market.get("outcomePrices", [])
        if isinstance(outcome_prices, str):
            import json

            try:
                outcome_prices = json.loads(outcome_prices)
            except Exception:
                outcome_prices = []

        odds_text = "N/A"
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                yes_odds = float(outcome_prices[0])
                no_odds = float(outcome_prices[1])
                odds_text = f"YES {yes_odds * 100:.0f}% | NO {no_odds * 100:.0f}%"
            except Exception:
                pass

        embed = {
            "title": "🆕 New Market",
            "description": market.get("question", "Unknown")[:300],
            "color": COLORS["NORMAL"],
            "fields": [
                {"name": "Odds", "value": odds_text, "inline": True},
                {"name": "Volume", "value": f"{vol_emoji} {vol_label}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

        if category:
            embed["fields"].append(
                {"name": "Category", "value": category, "inline": True}
            )

        market_id = market.get("id") or market.get("conditionId")
        if market_id:
            embed["url"] = f"https://polymarket.com/market/{market_id}"

        return {"embeds": [embed]}

    def format_volume_spike_alert(self, market: Dict) -> Dict:
        """Format volume spike alert."""
        ratio = market.get("volume_ratio", 0)
        volume = float(market.get("volume", 0) or 0)
        vol_emoji = get_volume_emoji(volume)

        embed = {
            "title": f"📈 Volume Spike: {ratio:.1f}x",
            "description": market.get("question", "Unknown")[:200],
            "color": COLORS["HIGH"],
            "fields": [
                {
                    "name": "Volume",
                    "value": f"{vol_emoji} ${volume:,.0f}",
                    "inline": True,
                }
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

        market_id = market.get("id")
        if market_id:
            embed["url"] = f"https://polymarket.com/market/{market_id}"

        return {"embeds": [embed]}

    def send_convergence_alert(
        self,
        market: Dict,
        wallets: List[Dict],
        threshold: float,
        convergence: Dict = None,
        positions: List[Dict] = None,
        check_cooldown: bool = True,
    ) -> bool:
        """Send convergence alert."""
        market_id = market.get("id") or market.get("conditionId") or "unknown"

        if check_cooldown and self.is_on_cooldown(market_id):
            return False

        payload = self.format_convergence_alert(
            market, wallets, threshold, convergence, positions
        )
        success = self.send_webhook(payload)

        if success:
            self.set_cooldown(market_id)

        return success

    def send_new_market_alert(self, market: Dict, category: str = None) -> bool:
        market_id = market.get("id") or market.get("conditionId") or "unknown"
        cooldown_key = f"new_{market_id}"

        if self.is_on_cooldown(cooldown_key):
            return False

        payload = self.format_new_market_alert(market, category)
        success = self.send_webhook(payload)

        if success:
            self.set_cooldown(cooldown_key)

        return success

    def send_volume_spike_alert(self, market: Dict) -> bool:
        market_id = market.get("id") or "unknown"

        if self.is_on_cooldown(f"spike_{market_id}"):
            return False

        payload = self.format_volume_spike_alert(market)
        success = self.send_webhook(payload)

        if success:
            self.set_cooldown(f"spike_{market_id}")

        return success

    def send_smart_money_alert(self, wallets: List[Dict]) -> bool:
        payload = self.format_smart_money_alert(wallets)
        return self.send_webhook(payload)

    def format_insider_alert(self, signal: Dict) -> Dict:
        """Format insider signal for Discord embed."""
        addr = signal.get("address", "Unknown")
        addr_short = addr[:10] + "..." if len(addr) > 10 else addr
        trade_size = signal.get("trade_size", 0)
        closed_count = signal.get("closed_count", 0)
        confidence = signal.get("confidence", "MEDIUM")
        win = signal.get("winning_trade") or {}
        question = (win.get("question") or "Unknown")[:150]
        pnl = win.get("pnl", 0)
        side = (win.get("side") or signal.get("side") or "?").upper()
        market_id = win.get("market_id", "")

        color = COLORS["CRITICAL"] if confidence == "HIGH" else (COLORS["HIGH"] if confidence == "MEDIUM" else COLORS["NORMAL"])
        embed = {
            "title": "🐋 Insider / Whale Signal",
            "description": f"Fresh wallet + large trade + winning outcome",
            "color": color,
            "fields": [
                {"name": "Address", "value": f"`{addr_short}`", "inline": True},
                {"name": "Trade Size", "value": f"${trade_size:,.0f}", "inline": True},
                {"name": "Closed Trades", "value": str(closed_count), "inline": True},
                {"name": "Winning Trade", "value": question, "inline": False},
                {"name": "PnL", "value": f"${pnl:,.2f}", "inline": True},
                {"name": "Side", "value": side, "inline": True},
                {"name": "Confidence", "value": confidence, "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        if market_id:
            embed["url"] = f"https://polymarket.com/market/{market_id}"
        return {"embeds": [embed]}

    def send_insider_alert(self, signal: Dict, check_cooldown: bool = True) -> bool:
        """Send insider signal alert to Discord."""
        addr = signal.get("address", "")
        win = signal.get("winning_trade") or {}
        market_id = win.get("market_id", "") or "unknown"
        cooldown_key = f"insider_{addr}_{market_id}"

        if check_cooldown and self.is_on_cooldown(cooldown_key):
            return False

        payload = self.format_insider_alert(signal)
        success = self.send_webhook(payload)
        if success:
            self.set_cooldown(cooldown_key)
        return success
