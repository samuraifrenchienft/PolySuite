"""Leaderboard importer for PolySuite."""

import requests
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from src.market.api import APIClientFactory


class LeaderboardImporter:
    """Import top traders from various sources."""

    def __init__(self, api_factory: APIClientFactory = None):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self.api_factory = api_factory
        self._polymarket_api = None
        self._predictfolio_client = None
        self._jupiter_client = None

    @property
    def polymarket_api(self):
        if self._polymarket_api is None and self.api_factory:
            self._polymarket_api = self.api_factory.get_polymarket_api()
        return self._polymarket_api

    @property
    def predictfolio_client(self):
        if self._predictfolio_client is None and self.api_factory:
            self._predictfolio_client = self.api_factory.get_predictfolio_client()
        return self._predictfolio_client

    @property
    def jupiter_client(self):
        if self._jupiter_client is None and self.api_factory:
            self._jupiter_client = self.api_factory.get_jupiter_prediction_client()
        return self._jupiter_client

    def fetch_leaderboard(self, limit: int = 50) -> List[Dict]:
        """Fetch the latest leaderboard from public sources."""
        all_wallets = {}

        # Try Polymarket Data API
        try:
            import requests

            resp = requests.get(
                "https://data-api.polymarket.com/v1/leaderboard",
                params={"category": "OVERALL", "limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for w in data:
                        addr = w.get("proxyWallet") or w.get("address")
                        if addr:
                            w["address"] = addr
                            w["source"] = "polymarket"
                            all_wallets[addr] = w
                    print(f"Fetched {len(all_wallets)} from Polymarket")
        except Exception as e:
            print(f"Error fetching Polymarket: {e}")

        return list(all_wallets.values())[:limit]

    def get_top_traders(self, limit: int = 20) -> List[Dict]:
        """Get top traders sorted by PnL/volume."""
        traders = self.fetch_leaderboard(limit=limit * 2)

        sorted_traders = []
        for t in traders:
            pnl = t.get("pnl") or t.get("volume") or 0
            try:
                pnl = float(str(pnl).replace("$", "").replace(",", ""))
            except:
                pnl = 0
            t["sort_value"] = pnl
            sorted_traders.append(t)

        sorted_traders.sort(key=lambda x: x.get("sort_value", 0), reverse=True)
        return sorted_traders[:limit]

    def get_wallet_stats(self, address: str) -> Optional[Dict]:
        """Get wallet stats."""
        if self.polymarket_api:
            try:
                return self.polymarket_api.get_wallet_stats(address)
            except:
                pass

        try:
            url = "https://gamma-api.polymarket.com/public-profile"
            resp = self.session.get(url, params={"address": address}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return {
                        "address": address,
                        "total_trades": data.get("totalTrades", 0),
                        "wins": data.get("wins", 0),
                        "win_rate": data.get("winRate", 0.0),
                        "volume": data.get("volume", 0),
                        "positions": data.get("positionsCount", 0),
                    }
        except Exception as e:
            print(f"Error fetching wallet stats: {e}")

        return None


if __name__ == "__main__":
    importer = LeaderboardImporter()
    traders = importer.fetch_leaderboard(limit=10)

    print(f"Found {len(traders)} top traders:\n")
    for i, t in enumerate(traders[:10], 1):
        source = t.get("source", "unknown")
        print(f"{i}. {t.get('address', 'N/A')[:20]}... [{source}]")
