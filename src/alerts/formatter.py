"""Alert formatter for clean, actionable alerts.

Each alert type has consistent formatting with:
- Clear title with emoji
- Actionable data
- Links where applicable
- AI reasoning when available
"""

from typing import Optional, Dict, List
from datetime import datetime


class AlertFormatter:
    """Format alerts for maximum clarity and actionability."""

    @staticmethod
    def format_new_market(
        event: dict,
        has_arb: bool = False,
        arb_profit: float = 0,
        sentiment: str = "",
        ai_insight: str = "",
        category: str = "",
    ) -> str:
        """Format new market alert."""
        question = event.get("question", "Unknown")[:100]
        volume = event.get("volume", 0)
        link = f"https://polymarket.com/market/{event.get('id', '')}"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🆕 **NEW MARKET**",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
        ]

        if has_arb:
            emoji = "🟢" if arb_profit >= 1.5 else ("🔵" if arb_profit >= 1.0 else "🟠")
            lines.insert(1, f"{emoji} **ARB: {arb_profit:.2f}%**")

        if category:
            lines.append(f"📁 Category: {category}")

        if sentiment and sentiment != "neutral":
            lines.append(f"📊 Sentiment: {sentiment.upper()}")

        if ai_insight:
            lines.append(f"🤖 {ai_insight[:120]}")

        lines.append(f"[View]({link})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_arb(arb: dict, ai_reasoning: str = "") -> str:
        """Format arbitrage alert."""
        question = arb.get("question", "Unknown")[:80]
        yes_price = float(arb.get("yes_price", 0))
        no_price = float(arb.get("no_price", 0))
        profit = float(arb.get("profit_pct", 0))

        emoji = "🟢" if profit >= 1.5 else ("🔵" if profit >= 1.0 else "🟠")

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"{emoji} **ARBITRAGE: {profit:.2f}%**",
            f"_{question}_",
            f"YES: ${yes_price:.2f} | NO: ${no_price:.2f}",
        ]

        if ai_reasoning:
            lines.append(f"🤖 {ai_reasoning[:150]}")

        market_id = arb.get("market_id") or arb.get("condition_id") or ""
        if market_id:
            lines.append(f"[View](https://polymarket.com/market/{market_id})")

        return "\n".join(lines)

    @staticmethod
    def format_convergence(
        market: dict, wallets: list, convergence: dict, ai_analysis: str = ""
    ) -> str:
        """Format convergence alert."""
        question = market.get("question", "Unknown")[:80]

        has_early = convergence.get("has_early_entry", False)
        urgency = (
            "CRITICAL"
            if (has_early and len(wallets) >= 3)
            else ("HIGH" if has_early or len(wallets) >= 3 else "NORMAL")
        )
        emoji = "🔴" if urgency == "CRITICAL" else ("🟠" if urgency == "HIGH" else "🔵")

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"{emoji} **CONVERGENCE - {urgency}**",
            f"_{question}_",
            f"👥 **{len(wallets)} traders** | Early: {'Yes' if has_early else 'No'}",
        ]

        if wallets:
            lines.append("")
            for w in wallets[:3]:
                wr = w.get("win_rate", 0)
                side = w.get("side", "?")
                ep = w.get("entry_price")
                size = w.get("size")
                parts = [f"• {w.get('nickname', '?')}"]
                if side and side != "?":
                    parts.append(f"{side}")
                if ep is not None:
                    parts.append(f"@ {ep:.2f}")
                if size and float(size) > 0:
                    parts.append(f"(${float(size):,.0f})")
                parts.append(f"| {wr:.0f}%")
                lines.append(" ".join(parts))

        if ai_analysis:
            lines.append(f"\n🤖 {ai_analysis[:120]}")

        market_id = market.get("id") or market.get("conditionId") or ""
        if market_id:
            lines.append(f"\n[View](https://polymarket.com/market/{market_id})")

        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_whale_batch(trades: list, ai_summary: str = "") -> str:
        """Format whale activity alert - cleaned up."""
        if not trades:
            return ""

        by_wallet = {}
        for t in trades:
            w = t.get("wallet", "Unknown")
            if w not in by_wallet:
                by_wallet[w] = []
            by_wallet[w].append(t)

        sorted_wallets = sorted(
            by_wallet.items(),
            key=lambda x: sum(t.get("size", 0) for t in x[1]),
            reverse=True,
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🐋 **WHALE ACTIVITY**",
            f"_{len(trades)} trades from {len(by_wallet)} wallets_",
            "",
        ]

        for wallet, wallet_trades in sorted_wallets[:5]:
            total = sum(t.get("size", 0) for t in wallet_trades)
            top = max(wallet_trades, key=lambda x: x.get("size", 0))
            question = top.get("question", "?")[:30]
            side = top.get("side", "?").upper()
            ep = top.get("entry_price")
            price_str = f" @ {ep:.2f}" if ep is not None else ""
            lines.append(f"**{wallet}** - ${total:,.0f}")
            lines.append(f"  {side}: ${top.get('size', 0):,.0f}{price_str} → {question}...")

        if len(sorted_wallets) > 5:
            lines.append(f"\n+{len(sorted_wallets) - 5} more wallets")

        if ai_summary:
            lines.append(f"\n🤖 {ai_summary[:100]}")

        return "\n".join(lines)

    @staticmethod
    def format_trend(token: dict, analysis: str = "") -> str:
        """Format pump.fun trend alert."""
        name = token.get("name", "Unknown")
        symbol = token.get("symbol", "?")
        mint = token.get("mint", "")[:20]

        lines = [
            f"🚨 **NEW TREND**",
            f"**{name}** (${symbol})",
            f"mint: `{mint}...`",
        ]

        if analysis:
            lines.append(f"\n🤖 {analysis[:150]}")

        return "\n".join(lines)

    @staticmethod
    def format_crypto_short_term(market: dict) -> str:
        """Format crypto 5M/15M/hourly market alert with question, time window, YES%, volume, link."""
        question = market.get("question", "Unknown")[:80]
        volume = float(market.get("volume", 0) or 0)
        yes_pct = market.get("yes_pct")
        link = f"https://polymarket.com/market/{market.get('id', '')}"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"⏱️ **CRYPTO 5M/15M**",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
        ]
        if yes_pct is not None:
            lines.append(f"📊 YES: {yes_pct * 100:.0f}% | NO: {(1 - yes_pct) * 100:.0f}%")
        lines.append(f"[View]({link})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_crypto_alert(
        symbol: str, price: float, change: float, source: str = ""
    ) -> str:
        """Format crypto price alert."""
        emoji = "🚀" if change > 0 else "📉"
        lines = [
            f"{emoji} **{symbol}**",
            f"${price:,.0f} ({change:+.1f}%)",
        ]
        if source:
            lines[0] += f" - {source}"
        return "\n".join(lines)

    @staticmethod
    def format_sports_market(market: dict) -> str:
        """Format sports market alert."""
        question = market.get("question", "Unknown")[:80]
        volume = float(market.get("volume", 0) or 0)
        link = f"https://polymarket.com/market/{market.get('id', '')}"
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "🏀 **SPORTS**",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
            f"[View]({link})",
        ]
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_kalshi_market(alert) -> str:
        """Format Kalshi market alert (MarketAlert from aggregator)."""
        q = getattr(alert, "question", alert.get("question", "Unknown"))[:80]
        vol = getattr(alert, "volume", alert.get("volume", 0)) or 0
        price = getattr(alert, "price", alert.get("price", 0.5)) or 0.5
        url = getattr(alert, "url", alert.get("url", ""))
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 **KALSHI**",
            f"_{q}_",
            f"💰 Vol: ${vol:,.0f}" if vol else "",
            f"📈 YES: {price*100:.0f}%" if price else "",
            f"[View]({url})" if url else "",
        ]
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_jupiter_market(alert) -> str:
        """Format Jupiter market alert (MarketAlert from aggregator)."""
        q = getattr(alert, "question", alert.get("question", "Unknown"))[:80]
        price = getattr(alert, "price", alert.get("price", 0.5)) or 0.5
        url = getattr(alert, "url", alert.get("url", ""))
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "🪐 **JUPITER**",
            f"_{q}_",
            f"📈 YES: {price*100:.0f}%" if price else "",
            f"[View]({url})" if url else "",
        ]
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_politics_market(market: dict) -> str:
        """Format politics market alert."""
        question = market.get("question", "Unknown")[:80]
        volume = float(market.get("volume", 0) or 0)
        link = f"https://polymarket.com/market/{market.get('id', '')}"
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "🗳️ **POLITICS**",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
            f"[View]({link})",
        ]
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_expiring(
        event: dict,
        event_title: str = "",
        yes_pct: float = None,
        spread: float = None,
    ) -> str:
        """Format expiring soon alert with game/event context and market consensus."""
        question = event.get("question", "Unknown")[:60]
        hours = event.get("hours_left", 0)
        mins = hours * 60

        emoji = "🔴" if hours < 0.5 else ("🟠" if hours < 1 else "🔵")

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"{emoji} **EXPIRING** ({mins:.0f}m left)",
            f"_{question}_",
        ]
        if event_title:
            lines.append(f"📌 {event_title}")
        if yes_pct is not None:
            lines.append(f"📊 Market: {yes_pct:.0%} YES / {100 - yes_pct * 100:.0f}% NO")
        if spread is not None and spread > 0:
            lines.append(f"📐 Spread: {spread:.2f}¢")
        return "\n".join(lines)

    @staticmethod
    def format_discord_embed(
        alert_type: str, content: str, color: int = 0x00FF00
    ) -> dict:
        """Format as Discord embed."""
        return {
            "embeds": [
                {
                    "title": alert_type,
                    "description": content,
                    "color": color,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ]
        }


formatter = AlertFormatter()
