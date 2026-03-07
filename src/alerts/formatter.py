"""Alert formatter for clean, actionable alerts.

Each alert type has consistent formatting with:
- Clear title with emoji
- Actionable data
- Links where applicable
- AI reasoning when available
"""

from typing import Optional, Dict, List
from datetime import datetime


def _polymarket_link(obj: dict) -> str:
    """Build working Polymarket URL. Prefer slug (event/market) over id/conditionId."""
    slug = obj.get("slug") or obj.get("eventSlug") or obj.get("event_slug")
    if slug and str(slug).strip():
        return f"https://polymarket.com/event/{slug}"
    mid = (
        obj.get("conditionId")
        or obj.get("market_id")
        or obj.get("id")
        or obj.get("condition_id")
        or ""
    )
    if mid:
        mid = str(mid).strip()
        return f"https://polymarket.com/market/{mid}"
    return ""


class AlertFormatter:
    """Format alerts for maximum clarity and actionability."""

    @staticmethod
    def format_new_market(
        event: dict,
        sentiment: str = "",
        ai_insight: str = "",
        category: str = "",
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format new market alert."""
        question = event.get("question", "Unknown")[:100]
        volume = event.get("volume", 0)
        link = (
            _polymarket_link(event)
            or f"https://polymarket.com/market/{event.get('id', '')}"
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🆕 **NEW MARKET**",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
        ]

        if category:
            lines.append(f"📁 Category: {category}")

        if sentiment and sentiment != "neutral":
            lines.append(f"📊 Sentiment: {sentiment.upper()}")

        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            rec_line = f"📌 RECOMMENDATION: {entry_zone}"
            if conviction:
                rec_line += f" | Confidence: {conviction}"
            lines.append(rec_line)
            if entry_reason:
                lines.append(f"   _{entry_reason[:100]}_")

        if ai_insight:
            lines.append(f"🤖 {ai_insight[:120]}")

        lines.append(f"[View]({link})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_convergence(
        market: dict,
        wallets: list,
        convergence: dict,
        ai_analysis: str = "",
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format convergence alert with optional RECOMMENDATION."""
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

        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            rec_line = f"📌 RECOMMENDATION: {entry_zone}"
            if conviction:
                rec_line += f" | Confidence: {conviction}"
            lines.append(rec_line)
            if entry_reason:
                lines.append(f"   _{entry_reason[:100]}_")

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

        link = (
            _polymarket_link(market)
            or f"https://polymarket.com/market/{market.get('id') or market.get('conditionId') or ''}"
        )
        if link:
            lines.append(f"\n[View]({link})")

        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_whale_batch(
        trades: list,
        ai_summary: str = "",
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format curated wallet activity alert with optional RECOMMENDATION."""
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
            f"📊 **CURATED WALLET ACTIVITY**",
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
            lines.append(
                f"  {side}: ${top.get('size', 0):,.0f}{price_str} → {question}..."
            )

        if len(sorted_wallets) > 5:
            lines.append(f"\n+{len(sorted_wallets) - 5} more wallets")

        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            rec_line = f"📌 RECOMMENDATION: {entry_zone}"
            if conviction:
                rec_line += f" | Confidence: {conviction}"
            lines.append(rec_line)
            if entry_reason:
                lines.append(f"   _{entry_reason[:100]}_")

        if ai_summary:
            lines.append(f"\n🤖 {ai_summary[:100]}")

        # Add link to top trade's market if available
        if trades and trades[0].get("market_id"):
            top = max(trades, key=lambda x: x.get("size", 0))
            link = (
                _polymarket_link(top)
                or f"https://polymarket.com/market/{top.get('market_id', '')}"
            )
            if link:
                lines.append(f"\n[View on Polymarket]({link})")

        return "\n".join(lines)

    @staticmethod
    def format_wallet_list(wallets: list) -> str:
        """Format weekly vetted wallet list: avg bet, win rate, bot score, top category."""
        if not wallets:
            return ""

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "📋 **WEEKLY VETTED WALLETS**",
            f"_{len(wallets)} wallets_",
            "",
        ]
        for i, w in enumerate(wallets[:30], 1):
            name = w.get("nickname", w.get("address", "?")[:12] + "...")
            avg = w.get("avg_bet_size", 0) or 0
            wr = w.get("win_rate_real", 0) or 0
            bot = w.get("bot_score") or "—"
            cat = (w.get("top_category") or "—").lower()
            streak = int(w.get("current_win_streak", 0) or 0)
            recent_wr = float(w.get("recent_win_rate", 0) or 0)
            reliability = w.get("reliability_score")
            rel_str = f"{float(reliability):.1f}" if reliability is not None else "—"
            lines.append(f"{i}. **{name}**")
            lines.append(
                f"   Avg ${avg:,.0f} | Win {wr:.0f}% | Recent {recent_wr:.0f}% | Streak {streak} | Rel {rel_str} | Bot {bot} | Top: {cat}"
            )
        return "\n".join(lines)

    @staticmethod
    def format_insider_signal(signal: dict) -> str:
        """Format insider signal alert (fresh wallet + large trade + winning)."""
        addr = signal.get("address", "Unknown")[:16] + "..."
        trade_size = signal.get("trade_size", 0)
        closed_count = signal.get("closed_count", 0)
        risk = signal.get("risk", "MEDIUM")
        confidence = signal.get("confidence", risk)
        win = signal.get("winning_trade") or {}
        question = (win.get("question") or "Unknown")[:60]
        pnl = win.get("pnl", 0)
        side = (win.get("side") or signal.get("side") or "UNKNOWN").upper()
        market_id = win.get("market_id", "")

        emoji = "🔴" if risk == "HIGH" else "🟠"

        # Build actionable message
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"{emoji} **INSIDER SIGNAL**",
            f"_{addr}_",
            f"📊 Fresh wallet: {closed_count} trades | ${trade_size:,.0f} size",
            f"✅ Winning: {question}... (+${pnl:,.2f})",
        ]
        if side in ("YES", "NO"):
            lines.append(f"🎯 Insider side: **{side}**")

        # Phase B: Risk signals
        signals = signal.get("signals") or {}
        if signals:
            parts = []
            if signals.get("fresh"):
                parts.append("Fresh")
            if signals.get("size_anomaly"):
                li = signal.get("liquidity_impact")
                pct = f" ({li:.1%} of book)" if li is not None else ""
                parts.append(f"Size anomaly{pct}")
            if signals.get("niche_market"):
                parts.append("Niche market")
            if parts:
                lines.append(f"📌 Signals: {', '.join(parts)}")

        # ACTIONABLE: Show what to do
        conf_level = {"HIGH": "🟢 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🟠 LOW"}.get(confidence, confidence)
        lines.append(f"⚠️ Confidence: {conf_level}")

        # Add copy-trade guidance
        if side in ("YES", "NO"):
            if confidence == "HIGH":
                lines.append(f"💡 Action: Consider **{side}** with larger position")
            elif confidence == "MEDIUM":
                lines.append(f"💡 Action: Consider **{side}** with medium position")
            else:
                lines.append(f"💡 Action: Consider **{side}** with small size only")
        else:
            if confidence == "HIGH":
                lines.append("💡 Action: Consider copy-trade with larger position")
            elif confidence == "MEDIUM":
                lines.append("💡 Action: Copy with medium position, watch closely")
            else:
                lines.append("💡 Action: Small position only for copy-trade edge")

        # Add market link if available
        if market_id:
            market_url = f"https://polymarket.com/market/{market_id}"
            lines.append(f"[View Market]({market_url})")
            if side in ("YES", "NO"):
                lines.append(f"💡 Check current odds; follow with **{side}** only if entry is favorable")
            else:
                lines.append("💡 Check current odds - bet same direction if favorable entry")

        lines.append(f"[View Wallet](https://polymarket.com/profile/{signal.get('address', '')})")
        return "\n".join(lines)

    @staticmethod
    def format_contrarian(signal: dict, source: str = "polymarket") -> str:
        """Format contrarian long-shot alert."""
        question = (signal.get("question") or "Unknown")[:70]
        vol_yes = signal.get("vol_yes", 0)
        vol_no = signal.get("vol_no", 0)
        majority = signal.get("majority_side", "?")
        minority = signal.get("minority_side", "?")
        minority_price = signal.get("minority_price", 0)
        payout = signal.get("payout", 0)
        total = signal.get("total_volume", 0)
        score = signal.get("score", 0)

        mid = signal.get("market_id", "")
        link = f"https://polymarket.com/market/{mid}" if mid else ""

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 **CONTRARIAN LONG-SHOT**",
            f"_{question}_",
            f"📈 Vol: YES ${vol_yes:,.0f} | NO ${vol_no:,.0f}",
            f"🎯 Crowd on {majority}; bet {minority} @ {minority_price:.2f} ({payout:.1f}x)",
            f"📐 Score: {score:.2f}",
            f"[View]({link})" if link else "",
        ]
        return "\n".join([l for l in lines if l])

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
    def format_crypto_short_term(
        market: dict,
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format crypto 5M/15M/hourly market alert with question, time window, YES%, volume, link."""
        question = market.get("question", "Unknown")[:80]
        volume = float(market.get("volume", 0) or 0)
        yes_pct = market.get("yes_pct")
        link = (
            _polymarket_link(market)
            or f"https://polymarket.com/market/{market.get('id', '')}"
        )

        # AUTO-OVERRIDE: Force BUY for extreme odds even if AI says WAIT
        if yes_pct is not None:
            if yes_pct < 0.15:
                entry_zone = "BUY_NO"
                conviction = "high"
                entry_reason = f"Clear value: NO at {(1 - yes_pct) * 100:.0f}% vs YES at {yes_pct * 100:.0f}%"
            elif yes_pct > 0.85:
                entry_zone = "BUY_YES"
                conviction = "high"
                entry_reason = f"Clear value: YES at {yes_pct * 100:.0f}% implied - high conviction"

        # Color code by confidence
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(conviction, "⚪")

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"⏱️ **CRYPTO 5M/15M UP/DOWN** {conf_emoji}",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
        ]
        if yes_pct is not None:
            lines.append(
                f"📊 YES: {yes_pct * 100:.0f}% | NO: {(1 - yes_pct) * 100:.0f}%"
            )
        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            # Make recommendation clearer
            side = (
                "YES"
                if "YES" in entry_zone
                else "NO"
                if "NO" in entry_zone
                else entry_zone
            )
            lines.append(f"🎯 **{side}** (confidence: {conviction})")
            if entry_reason:
                lines.append(f"   💡 {entry_reason[:100]}")
        else:
            lines.append("⏸️ WAIT - no clear signal")
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
    def format_sports_market(
        market: dict,
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format sports market alert."""
        import json

        question = market.get("question", "Unknown")[:80]
        volume = float(market.get("volume", 0) or 0)
        link = (
            _polymarket_link(market)
            or f"https://polymarket.com/market/{market.get('id', '')}"
        )

        # Get YES% for auto-detection
        yes_pct = market.get("yes_pct")
        if yes_pct is None:
            raw_prices = market.get("outcomePrices")
            prices = (
                json.loads(raw_prices)
                if isinstance(raw_prices, str)
                else (raw_prices or [])
            )
            yes_pct = float(prices[0]) if prices and len(prices) >= 1 else 0.5

        # Auto-detect clear signals from extreme odds
        if yes_pct < 0.15:
            entry_zone = "BUY_NO"
            conviction = "high"
            entry_reason = f"Clear value: NO at {(1 - yes_pct) * 100:.0f}% vs YES at {yes_pct * 100:.0f}%"
        elif yes_pct > 0.85:
            entry_zone = "BUY_YES"
            conviction = "high"
            entry_reason = (
                f"Clear value: YES at {yes_pct * 100:.0f}% implied - high conviction"
            )

        # Color code by confidence
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(conviction, "⚪")

        # Show odds based on recommendation
        if entry_zone and "NO" in entry_zone:
            odds_str = f"📊 NO: {(1 - yes_pct) * 100:.0f}%"
        elif entry_zone and "YES" in entry_zone:
            odds_str = f"📊 YES: {yes_pct * 100:.0f}%"
        else:
            odds_str = f"📊 YES: {yes_pct * 100:.0f}% | NO: {(1 - yes_pct) * 100:.0f}%"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🏀 **SPORTS** {conf_emoji}",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
            odds_str,
        ]
        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            side = (
                "YES"
                if "YES" in entry_zone
                else "NO"
                if "NO" in entry_zone
                else entry_zone
            )
            lines.append(f"🎯 **{side}** (confidence: {conviction})")
            if entry_reason:
                lines.append(f"   💡 {entry_reason[:100]}")
        else:
            lines.append("⏸️ WAIT - no clear signal")
        lines.append(f"[View]({link})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_kalshi_market(
        alert,
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format Kalshi market alert (MarketAlert from aggregator)."""
        q = (
            alert.get("question", "Unknown")
            if isinstance(alert, dict)
            else getattr(alert, "question", "Unknown")
        )[:80]
        if isinstance(alert, dict):
            vol = alert.get("volume", 0) or 0
            price = alert.get("price", 0.5) or 0.5
            url = alert.get("url", "")
        else:
            vol = getattr(alert, "volume", 0) or 0
            price = getattr(alert, "price", 0.5) or 0.5
            url = getattr(alert, "url", "")

        # Auto-detect clear signals from extreme odds
        if price < 0.15:
            entry_zone = "BUY_NO"
            conviction = "high"
            entry_reason = f"Clear value: NO at {(1 - price) * 100:.0f}% vs YES at {price * 100:.0f}%"
        elif price > 0.85:
            entry_zone = "BUY_YES"
            conviction = "high"
            entry_reason = (
                f"Clear value: YES at {price * 100:.0f}% implied - high conviction"
            )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"📊 **KALSHI**",
            f"_{q}_",
            f"💰 Vol: ${vol:,.0f}" if vol else "",
            f"📈 YES: {price * 100:.0f}%" if price else "",
        ]
        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            side = (
                "YES"
                if "YES" in entry_zone
                else "NO"
                if "NO" in entry_zone
                else entry_zone
            )
            lines.append(f"🎯 **{side}** (confidence: {conviction})")
            if entry_reason:
                lines.append(f"   💡 {entry_reason[:100]}")
        else:
            lines.append("⏸️ WAIT - no clear signal")
        if url:
            lines.append(f"[View]({url})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_jupiter_market(
        alert,
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format Jupiter market alert (MarketAlert from aggregator)."""
        q = (
            alert.get("question", "Unknown")
            if isinstance(alert, dict)
            else getattr(alert, "question", "Unknown")
        )[:80]
        if isinstance(alert, dict):
            price = alert.get("price", 0.5) or 0.5
            vol = alert.get("volume", 0) or 0
            url = alert.get("url", "")
            cat = alert.get("category", "crypto") or "crypto"
        else:
            price = getattr(alert, "price", 0.5) or 0.5
            vol = getattr(alert, "volume", 0) or 0
            url = getattr(alert, "url", "")
            cat = getattr(alert, "category", "crypto") or "crypto"

        # Fallback: detect category from question keywords
        q_lower = q.lower()
        if cat == "other" or cat == "crypto":
            politics_kw = [
                "president",
                "election",
                "trump",
                "biden",
                "congress",
                "senate",
                "clinton",
                "chelsea",
                "harris",
                "democratic",
                "republican",
            ]
            sports_kw = [
                "nba",
                "nfl",
                "nhl",
                "mlb",
                "football",
                "basketball",
                "soccer",
                "tennis",
                "golf",
                "world series",
                "finals",
            ]
            if any(kw in q_lower for kw in politics_kw):
                cat = "politics"
            elif any(kw in q_lower for kw in sports_kw):
                cat = "sports"

        # Auto-detect clear signals from extreme odds
        if price < 0.15:
            entry_zone = "BUY_NO"
            conviction = "high"
            entry_reason = f"Clear value: NO at {(1 - price) * 100:.0f}% vs YES at {price * 100:.0f}%"
        elif price > 0.85:
            entry_zone = "BUY_YES"
            conviction = "high"
            entry_reason = (
                f"Clear value: YES at {price * 100:.0f}% implied - high conviction"
            )

        # Map category to emoji/label
        cat_label = {
            "crypto": "🪐 JUPITER",
            "crypto_short_term": "⏱️ CRYPTO 5M/15M UP/DOWN",
            "sports": "🏀 SPORTS",
            "politics": "🗳️ POLITICS",
            "world": "🌍 WORLD",
        }.get(cat, f"🪐 {cat.upper()}")

        # Color code by confidence
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(conviction, "⚪")

        # Show odds based on recommendation
        if entry_zone and "NO" in entry_zone:
            odds_str = f"📈 NO: {(1 - price) * 100:.0f}%"
        elif entry_zone and "YES" in entry_zone:
            odds_str = f"📈 YES: {price * 100:.0f}%"
        else:
            odds_str = f"📈 YES: {price * 100:.0f}% | NO: {(1 - price) * 100:.0f}%"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"**{cat_label}** {conf_emoji}",
            f"_{q}_",
            f"💰 Vol: ${vol:,.0f}" if vol else "",
            odds_str if price else "",
        ]
        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            side = (
                "YES"
                if "YES" in entry_zone
                else "NO"
                if "NO" in entry_zone
                else entry_zone
            )
            lines.append(f"🎯 **{side}** (confidence: {conviction})")
            if entry_reason:
                lines.append(f"   💡 {entry_reason[:100]}")
        else:
            lines.append("⏸️ WAIT - no clear signal")
        if url:
            lines.append(f"[View]({url})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_politics_market(
        market: dict,
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format politics market alert."""
        import json

        question = market.get("question", "Unknown")[:80]
        volume = float(market.get("volume", 0) or 0)
        link = (
            _polymarket_link(market)
            or f"https://polymarket.com/market/{market.get('id', '')}"
        )

        # Get YES% for auto-detection
        yes_pct = market.get("yes_pct")
        if yes_pct is None:
            raw_prices = market.get("outcomePrices")
            prices = (
                json.loads(raw_prices)
                if isinstance(raw_prices, str)
                else (raw_prices or [])
            )
            yes_pct = float(prices[0]) if prices and len(prices) >= 1 else 0.5

        # Auto-detect clear signals from extreme odds
        if yes_pct < 0.15:
            entry_zone = "BUY_NO"
            conviction = "high"
            entry_reason = f"Clear value: NO at {(1 - yes_pct) * 100:.0f}% vs YES at {yes_pct * 100:.0f}%"
        elif yes_pct > 0.85:
            entry_zone = "BUY_YES"
            conviction = "high"
            entry_reason = (
                f"Clear value: YES at {yes_pct * 100:.0f}% implied - high conviction"
            )

        # Color code by confidence
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(conviction, "⚪")

        # Show odds based on recommendation
        if entry_zone and "NO" in entry_zone:
            odds_str = f"📊 NO: {(1 - yes_pct) * 100:.0f}%"
        elif entry_zone and "YES" in entry_zone:
            odds_str = f"📊 YES: {yes_pct * 100:.0f}%"
        else:
            odds_str = f"📊 YES: {yes_pct * 100:.0f}% | NO: {(1 - yes_pct) * 100:.0f}%"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🗳️ **POLITICS** {conf_emoji}",
            f"_{question}_",
            f"💰 Volume: ${volume:,.0f}" if volume else "",
            odds_str,
        ]
        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            side = (
                "YES"
                if "YES" in entry_zone
                else "NO"
                if "NO" in entry_zone
                else entry_zone
            )
            lines.append(f"🎯 **{side}** (confidence: {conviction})")
            if entry_reason:
                lines.append(f"   💡 {entry_reason[:100]}")
        else:
            lines.append("⏸️ WAIT - no clear signal")
        lines.append(f"[View]({link})")
        return "\n".join([l for l in lines if l])

    @staticmethod
    def format_expiring(
        event: dict,
        event_title: str = "",
        yes_pct: float = None,
        spread: float = None,
        entry_zone: str = "",
        conviction: str = "",
        entry_reason: str = "",
    ) -> str:
        """Format expiring soon alert with optional RECOMMENDATION."""
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
            lines.append(
                f"📊 Market: {yes_pct:.0%} YES / {100 - yes_pct * 100:.0f}% NO"
            )
        if spread is not None and spread > 0:
            lines.append(f"📐 Spread: {spread:.2f}¢")
        if entry_zone and entry_zone not in ("WAIT", "AVOID"):
            rec_line = f"📌 RECOMMENDATION: {entry_zone}"
            if conviction:
                rec_line += f" | Confidence: {conviction}"
            lines.append(rec_line)
            if entry_reason:
                lines.append(f"   _{entry_reason[:100]}_")
        link = (
            _polymarket_link(event)
            or f"https://polymarket.com/market/{event.get('id') or event.get('conditionId') or ''}"
        )
        if link:
            lines.append(f"[View]({link})")
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
