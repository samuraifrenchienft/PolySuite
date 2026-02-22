"""Discord embed formatting for alerts."""
from typing import List, Dict, Optional
from datetime import datetime


class AlertFormatter:
    """Formats alerts for Discord webhooks."""

    @staticmethod
    def format_convergence_alert(
        market: Dict,
        wallets: List[Dict],
        threshold: float
    ) -> Dict:
        """Format convergence alert as Discord embed.

        Args:
            market: Market information
            wallets: List of converging wallets
            threshold: Win rate threshold used

        Returns:
            Discord webhook payload
        """
        # Build wallet list text
        wallet_lines = []
        for w in wallets:
            line = f"**{w['nickname']}** — {w['win_rate']:.1f}% ({w['wins']}/{w['total_trades']} trades)"
            wallet_lines.append(line)

        wallet_text = "\n".join(wallet_lines)

        # Market info
        question = market.get("question", "Unknown")[:200]
        volume = market.get("volume", 0)
        liquidity = market.get("liquidity", 0)
        outcome_prices = market.get("outcomePrices", "[]")

        # Parse outcome prices if possible
        prices_text = ""
        try:
            import json
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            if prices and len(prices) >= 2:
                prices_text = f"Yes: {prices[0]} | No: {prices[1]}"
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Error parsing outcome prices: {e}")

        # Build embed
        embed = {
            "title": "🔥 Convergence Alert",
            "description": f"**{len(wallets)}** high-performers detected in the same market\n"
                          f"Win rate threshold: **{threshold}%**+\n\n"
                          f"{wallet_text}",
            "color": 0xFF6B6B,  # Red-ish
            "fields": [
                {
                    "name": "📊 Market",
                    "value": question,
                    "inline": False
                }
            ],
            "timestamp": datetime.utcnow().isoformat()
        }

        # Add volume field
        embed["fields"].append({
            "name": "💰 Volume",
            "value": f"${volume:,.0f}" if isinstance(volume, (int, float)) else str(volume),
            "inline": True
        })

        # Add liquidity field
        embed["fields"].append({
            "name": "💵 Liquidity",
            "value": f"${liquidity:,.0f}" if isinstance(liquidity, (int, float)) else str(liquidity),
            "inline": True
        })

        # Add odds if available
        if prices_text:
            embed["fields"].append({
                "name": "📈 Odds",
                "value": prices_text,
                "inline": True
            })

        # Add Polymarket link
        market_id = market.get("id") or market.get("conditionId")
        if market_id:
            embed["url"] = f"https://polymarket.com/market/{market_id}"

        return {"embeds": [embed]}

    @staticmethod
    def format_new_market_alert(market: Dict) -> Dict:
        """Format new market alert as Discord embed.

        Args:
            market: Market information

        Returns:
            Discord webhook payload
        """
        question = market.get("question", "Unknown")[:250]
        volume = market.get("volume", 0)
        category = market.get("groupItemTitle", "General")

        embed = {
            "title": "🆕 New Market Detected",
            "description": question,
            "color": 0x00FF00,  # Green
            "fields": [
                {
                    "name": "📂 Category",
                    "value": category,
                    "inline": True
                },
                {
                    "name": "💰 Volume",
                    "value": f"${volume:,.0f}" if isinstance(volume, (int, float)) else str(volume),
                    "inline": True
                }
            ],
            "timestamp": datetime.utcnow().isoformat()
        }

        market_id = market.get("id") or market.get("conditionId")
        if market_id:
            embed["url"] = f"https://polymarket.com/market/{market_id}"

        return {"embeds": [embed]}

    @staticmethod
    def format_wallet_alert(wallet: Dict) -> Dict:
        """Format wallet update alert as Discord embed.

        Args:
            wallet: Wallet information

        Returns:
            Discord webhook payload
        """
        nickname = wallet.get("nickname", "Unknown")
        win_rate = wallet.get("win_rate", 0)
        wins = wallet.get("wins", 0)
        total = wallet.get("total_trades", 0)

        embed = {
            "title": "👤 Wallet Updated",
            "description": f"**{nickname}** stats updated",
            "color": 0x3498DB,  # Blue
            "fields": [
                {
                    "name": "📊 Win Rate",
                    "value": f"{win_rate:.1f}%",
                    "inline": True
                },
                {
                    "name": "🎯 Record",
                    "value": f"{wins}/{total}",
                    "inline": True
                }
            ],
            "timestamp": datetime.utcnow().isoformat()
        }

        return {"embeds": [embed]}
