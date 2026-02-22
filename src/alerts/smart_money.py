"""Alert for newly detected smart money wallets."""

from typing import List, Dict


def format_smart_money_alert(wallets: List[Dict]) -> str:
    """Format a message for a smart money alert."""
    lines = [
        "🧠 *SMART MONEY DETECTED*",
        f"_{len(wallets)} new high-performing wallet(s)_",
        "",
    ]

    for w in wallets:
        nickname = w.get("nickname", "Unknown")
        addr = w.get("address", "Unknown")[:10]
        win_rate = w.get("win_rate", 0)
        trades = w.get("total_trades", 0)
        wins = w.get("wins", 0)
        volume = w.get("trade_volume", 0)

        # Color code win rate
        if win_rate >= 65:
            wr_emoji = "🟢"
        elif win_rate >= 55:
            wr_emoji = "🟡"
        else:
            wr_emoji = "🔴"

        lines.append(f"*{nickname}* (`{addr}...`)")
        lines.append(
            f"  {wr_emoji} {win_rate:.1f}% | {wins}/{trades} trades | ${volume:,.0f}"
        )
        lines.append("")

    lines.append("[View on Polymarket](https://polymarket.com/leaderboard)")

    return "\n".join(lines)
