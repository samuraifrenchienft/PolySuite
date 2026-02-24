"""Alert pipeline - fetch, filter, format, send.

Flow:
1. Fetch data from sources
2. Filter for quality
3. Format with AlertFormatter
4. Send to appropriate channel

NO AI analysis - that's for user chat only via Groq.
"""

from typing import List, Dict
from src.alerts.formatter import formatter
from src.config import Config


class AlertPipeline:
    """Alert processing pipeline - simple, no AI."""

    def __init__(self, config: Config = None):
        self.config = config or Config()

    def filter_arbs(self, arbs: List[dict]) -> List[dict]:
        """Filter arbs for quality."""
        filtered = []
        for arb in arbs:
            try:
                profit = float(arb.get("profit_pct", 0))
                if profit >= 0.5:  # Minimum 0.5%
                    filtered.append(arb)
            except:
                pass
        return filtered

    def filter_whales(self, trades: List[dict]) -> List[dict]:
        """Filter whale trades for significance."""
        if not trades:
            return []
        total = sum(t.get("size", 0) for t in trades)
        if total >= 50000:  # $50k minimum
            return trades
        return []

    def filter_convergences(self, convs: List[dict]) -> List[dict]:
        """Filter convergences for quality."""
        return [c for c in convs if len(c.get("wallets", [])) >= 2]

    def filter_new_markets(self, markets: List[dict]) -> List[dict]:
        """Filter new markets - only crypto/politics/sports."""
        categories = ["crypto", "politics", "sports", "economy"]
        filtered = []
        for m in markets:
            cat = m.get("category", "").lower()
            if any(c in cat for c in categories):
                filtered.append(m)
        return filtered

    def filter_trends(self, tokens: List[dict]) -> List[dict]:
        """Filter pump.fun trends."""
        filtered = []
        for t in tokens:
            try:
                mc = float(t.get("usd_market_cap", 0) or 0)
                if mc >= 50000:  # $50k min
                    filtered.append(t)
            except:
                pass
        return filtered


# Singleton
pipeline = AlertPipeline()
