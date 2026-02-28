"""Polymarket Data API - free replacement for HashDive whale trades.

Uses https://data-api.polymarket.com/trades with filterType=CASH and filterAmount
to get platform-wide large trades. No API key required.
"""

import requests
from typing import List, Dict

DATA_API = "https://data-api.polymarket.com"


class PolymarketWhaleClient:
    """Free client for large Polymarket trades via Data API."""

    def get_latest_whale_trades(self, min_usd: int = 5000, limit: int = 50) -> List[Dict]:
        """Get latest large trades (free, no API key).

        Args:
            min_usd: Minimum trade value in USD (filterAmount)
            limit: Number of trades to return

        Returns:
            List of trade dicts with address, wallet, size, etc.
        """
        try:
            resp = requests.get(
                f"{DATA_API}/trades",
                params={
                    "filterType": "CASH",
                    "filterAmount": min_usd,
                    "limit": limit,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            if not isinstance(data, list):
                return []

            # Normalize to HashDive-like format for insider_signal
            out = []
            for t in data:
                addr = t.get("proxyWallet") or t.get("address")
                if not addr:
                    continue
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                usd = size * price if price else size
                out.append({
                    "address": addr,
                    "wallet": addr,
                    "size": usd,
                    "usdSize": usd,
                    **t,
                })
            return out
        except Exception as e:
            print(f"[-] Polymarket whale trades failed: {e}")
        return []
