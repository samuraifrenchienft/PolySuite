"""QuickChart integration for PolySuite."""
import urllib.parse
from typing import List, Dict, Optional


class QuickChartClient:
    """Generate charts using QuickChart.io."""

    BASE_URL = "https://quickchart.io/chart"

    def __init__(self, api_key: str = None):
        """Initialize with optional API key."""
        self.api_key = api_key

    def generate_url(self, config: dict) -> str:
        """Generate chart URL from config.

        Args:
            config: Chart.js compatible config

        Returns:
            Chart image URL
        """
        import json
        chart_config = urllib.parse.quote(json.dumps(config))
        url = f"{self.BASE_URL}?c={chart_config}"
        if self.api_key:
            url += f"&apiKey={self.api_key}"
        return url

    def wallet_performance_chart(
        self,
        wallets: List[Dict],
        title: str = "Wallet Performance"
    ) -> str:
        """Generate bar chart of wallet win rates.

        Args:
            wallets: List of wallet dicts with nickname, win_rate
            title: Chart title

        Returns:
            Chart image URL
        """
        # Sort by win rate descending
        sorted_wallets = sorted(wallets, key=lambda w: w.get("win_rate", 0), reverse=True)
        top_wallets = sorted_wallets[:10]  # Top 10

        labels = [w.get("nickname", w.get("address", "")[:8]) for w in top_wallets]
        data = [round(w.get("win_rate", 0), 1) for w in top_wallets]

        # Color by performance
        colors = []
        for w in top_wallets:
            rate = w.get("win_rate", 0)
            if rate >= 70:
                colors.append("#22c55e")  # green
            elif rate >= 55:
                colors.append("#eab308")  # yellow
            else:
                colors.append("#ef4444")  # red

        config = {
            "type": "bar",
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": "Win Rate %",
                    "data": data,
                    "backgroundColor": colors
                }]
            },
            "options": {
                "plugins": {
                    "legend": {"display": False},
                    "title": {
                        "display": True,
                        "text": title,
                        "font": {"size": 16}
                    }
                },
                "scales": {
                    "y": {
                        "beginAtZero": True,
                        "max": 100,
                        "title": {"display": True, "text": "Win Rate %"}
                    }
                }
            }
        }

        return self.generate_url(config)

    def convergence_chart(
        self,
        market_name: str,
        wallets: List[Dict]
    ) -> str:
        """Generate chart for convergence (traders in same market).

        Args:
            market_name: Market question
            wallets: List of wallets in this market

        Returns:
            Chart image URL
        """
        labels = [w.get("nickname", w.get("address", "")[:8]) for w in wallets]
        win_rates = [round(w.get("win_rate", 0), 1) for w in wallets]

        config = {
            "type": "horizontalBar",
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": "Win Rate %",
                    "data": win_rates,
                    "backgroundColor": "#3b82f6"
                }]
            },
            "options": {
                "plugins": {
                    "legend": {"display": False},
                    "title": {
                        "display": True,
                        "text": f"Convergence: {market_name[:40]}...",
                        "font": {"size": 14}
                    }
                },
                "scales": {
                    "x": {
                        "beginAtZero": True,
                        "max": 100,
                        "title": {"display": True, "text": "Win Rate %"}
                    }
                }
            }
        }

        return self.generate_url(config)

    def market_volume_chart(
        self,
        markets: List[Dict],
        title: str = "Top Markets by Volume"
    ) -> str:
        """Generate pie chart of market volumes.

        Args:
            markets: List of market dicts with question, volume
            title: Chart title

        Returns:
            Chart image URL
        """
        # Sort by volume descending
        sorted_markets = sorted(markets, key=lambda m: m.get("volume", 0), reverse=True)
        top_markets = sorted_markets[:8]

        labels = [m.get("question", "Unknown")[:25] + "..." for m in top_markets]
        volumes = [round(m.get("volume", 0), 0) for m in top_markets]

        config = {
            "type": "pie",
            "data": {
                "labels": labels,
                "datasets": [{
                    "data": volumes,
                    "backgroundColor": [
                        "#3b82f6", "#22c55e", "#eab308", "#ef4444",
                        "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"
                    ]
                }]
            },
            "options": {
                "plugins": {
                    "legend": {"position": "right"},
                    "title": {
                        "display": True,
                        "text": title,
                        "font": {"size": 16}
                    }
                }
            }
        }

        return self.generate_url(config)
