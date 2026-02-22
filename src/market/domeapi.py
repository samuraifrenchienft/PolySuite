"""DomeAPI client for Polymarket market data."""
import requests
from typing import List, Dict, Optional


class DomeAPI:
    """Client for DomeAPI Polymarket integration."""

    BASE_URL = "https://api.domeapi.io/v1/polymarket"

    def __init__(self, api_key: str = None):
        """Initialize with API key."""
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def get_market(self, market_slug: str) -> Optional[Dict]:
        """Get market data by slug.

        Args:
            market_slug: Market slug (e.g., 'will-gavin-newsom-win-the-2028-us-presidential-election')

        Returns:
            Market data dict or None
        """
        if not self.api_key:
            print("[-] DomeAPI key not configured")
            return None

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/markets",
                params={"market_slug": market_slug},
                timeout=30
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from DomeAPI: {e}")
                    return None
                return data if isinstance(data, dict) else None
            else:
                print(f"[-] DomeAPI error: {resp.status_code}")
        except requests.RequestException as e:
            print(f"[-] DomeAPI request failed: {e}")

        return None

    def close(self):
        """Close the session."""
        self.session.close()
        """Get market data by condition ID."""
        if not self.api_key:
            return None

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/markets/{condition_id}",
                timeout=30
            )
            if resp.status_code == 200:
                try:
                    return resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from DomeAPI: {e}")
                    return None
        except requests.RequestException as e:
            print(f"[-] DomeAPI request failed: {e}")

        return None
