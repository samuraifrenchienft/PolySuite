"""HashDive API client for whale trade tracking."""
import requests
from typing import List, Dict, Optional


class HashdiveClient:
    """Client for HashDive whale tracking API."""

    BASE_URL = "https://hashdive.com/api"

    def __init__(self, api_key: str = None):
        """Initialize with API key."""
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"x-api-key": api_key})

    def get_latest_whale_trades(self, min_usd: int = 20000, limit: int = 50) -> List[Dict]:
        """Get latest whale trades.

        Args:
            min_usd: Minimum trade value in USD
            limit: Number of trades to return

        Returns:
            List of whale trade dicts
        """
        if not self.api_key:
            print("[-] HashDive API key not configured")
            return []

        min_usd = max(0, min(1_000_000, int(min_usd)))
        limit = max(1, min(100, int(limit)))
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/get_latest_whale_trades",
                params={"min_usd": min_usd, "format": "json", "limit": limit},
                timeout=30
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from Hashdive: {e}")
                    return None
                return data if isinstance(data, list) else []
            else:
                print(f"[-] HashDive API error: {resp.status_code}")
        except requests.RequestException as e:
            print(f"[-] HashDive request failed: {e}")

        return []

    def get_whale_wallets(self, min_usd: int = 20000, limit: int = 20) -> List[str]:
        """Get unique whale wallet addresses.

        Args:
            min_usd: Minimum trade value
            limit: Max wallets to return

        Returns:
            List of wallet addresses
        """
        trades = self.get_latest_whale_trades(min_usd=min_usd, limit=limit * 2)
        wallets = []
        seen = set()

        for trade in trades:
            addr = trade.get("address") or trade.get("wallet")
            if addr and addr.lower() not in seen:
                seen.add(addr.lower())
                wallets.append(addr)
                if len(wallets) >= limit:
                    break

        return wallets

    def close(self):
        """Close the session."""
        self.session.close()
