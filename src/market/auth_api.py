"""Authenticated Polymarket API client for PolySuite."""

import requests
import base64
import time
from typing import List, Dict, Optional
import json


class AuthenticatedPolymarketAPI:
    """Authenticated Polymarket API client using builder credentials."""

    def __init__(self, api_key: str, api_secret: str, api_passphrase: str):
        """Initialize with API credentials."""
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.base_url = "https://clob.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )

    def _generate_signature(self, method: str, path: str, body: str = "") -> str:
        """Generate authentication signature."""
        import hmac
        import hashlib

        timestamp = str(int(time.time()))
        message = timestamp + method + path + body

        secret_decoded = base64.b64decode(self.api_secret)
        signature = hmac.new(secret_decoded, message.encode(), hashlib.sha256).digest()
        return base64.b64encode(signature).decode()

    def _auth_request(
        self, method: str, endpoint: str, data: dict = None
    ) -> Optional[dict]:
        """Make authenticated request."""
        url = self.base_url + endpoint
        body = json.dumps(data) if data else ""

        headers = {
            "POLY-API-KEY": self.api_key,
            "POLY-API-PASSPHRASE": self.api_passphrase,
            "POLY-API-TIMESTAMP": str(int(time.time())),
        }

        headers["POLY-API-SIGNATURE"] = self._generate_signature(method, endpoint, body)

        try:
            if method == "GET":
                resp = self.session.get(url, headers=headers, timeout=30)
            elif method == "POST":
                resp = self.session.post(url, headers=headers, data=body, timeout=30)
            resp.raise_for_status()
            try:
                return resp.json()
            except requests.exceptions.JSONDecodeError as e:
                print(f"Error decoding JSON from Polymarket authenticated API: {e}")
                return None
        except requests.RequestException as e:
            print(f"API error: {e}")
            return None

    def get_user_profile(self, address: str) -> Optional[dict]:
        """Get user profile and stats."""
        # Try gamma API first (public)
        url = f"https://gamma-api.polymarket.com/public-profile?address={address}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from user profile: {e}")
                    return None
        except requests.RequestException as e:
            print(f"Error fetching user profile for {address}: {e}")
        return None

    def get_user_positions(self, address: str) -> List[dict]:
        """Get user's current positions."""
        url = f"https://data-api.polymarket.com/positions?user={address}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from user positions: {e}")
                    return []
        except requests.RequestException as e:
            print(f"Error fetching user positions for {address}: {e}")
        return []

    def get_user_trades(self, address: str, limit: int = 100) -> List[dict]:
        """Get user's trade history."""
        url = f"https://data-api.polymarket.com/trades?user={address}&limit={limit}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from user trades: {e}")
                    return []
        except requests.RequestException as e:
            print(f"Error fetching user trades for {address}: {e}")
        return []

    def get_user_activity(self, address: str, limit: int = 100) -> List[dict]:
        """Get user's activity."""
        url = f"https://data-api.polymarket.com/activity?user={address}&limit={limit}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON from user activity: {e}")
                    return []
        except requests.RequestException as e:
            print(f"Error fetching user activity for {address}: {e}")
        return []

    def get_wallet_stats(self, address: str) -> dict:
        """Get comprehensive wallet stats."""
        trades = self.get_user_trades(address, 500)
        positions = self.get_user_positions(address)

        # Calculate stats
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "address": address,
                "total_trades": 0,
                "wins": 0,
                "win_rate": 0.0,
                "volume": 0,
                "positions": 0,
            }

        wins = 0
        volume = 0

        for trade in trades:
            side = trade.get("side", "").upper()
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            volume += size

            # Buy Yes at < 0.5 = potentially winning (bought cheap)
            if side == "BUY" and price < 0.5:
                wins += 1
            # Sell Yes at > 0.5 = potentially winning (sold expensive)
            elif side == "SELL" and price > 0.5:
                wins += 1

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        # Get position count
        position_count = len(positions)

        return {
            "address": address,
            "total_trades": total_trades,
            "wins": wins,
            "win_rate": win_rate,
            "volume": volume,
            "positions": position_count,
        }

    def get_wallet_positions(self, address: str) -> List[Dict]:
        """Get current positions for a wallet."""
        return self.get_user_positions(address)

    def get_wallet_trades(self, address: str, limit: int = 100) -> List[Dict]:
        """Get trade history for a wallet."""
        return self.get_user_trades(address, limit)

    def get_leaderboard(self, limit: int = 50) -> List[Dict]:
        """Get top traders from Polymarket."""
        try:
            url = "https://gamma-api.polymarket.com/leaderboards"
            resp = self.session.get(url, params={"limit": limit}, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                if isinstance(result, list):
                    return result
        except Exception as e:
            print(f"Error fetching Polymarket leaderboard: {e}")
        return []

    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get market details."""
        try:
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"Error fetching market: {e}")
        return None

    def get_markets(self, limit: int = 100, active: bool = True) -> List[Dict]:
        """Get markets."""
        try:
            url = "https://gamma-api.polymarket.com/markets"
            params = {"limit": limit}
            if active:
                params["closed"] = "false"
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"Error fetching markets: {e}")
        return []

    def get_active_markets(self, limit: int = 50) -> List[Dict]:
        """Get active markets."""
        return self.get_markets(limit=limit, active=True)

    def get_wallet_positions(self, address: str) -> List[Dict]:
        """Get current positions for a wallet."""
        return self.get_user_positions(address)

    def get_wallet_trades(self, address: str, limit: int = 100) -> List[Dict]:
        """Get trade history for a wallet."""
        return self.get_user_trades(address, limit)

    def close(self):
        """Close the session."""
        self.session.close()
