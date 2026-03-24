"""Authenticated Polymarket API client for PolySuite."""

import logging
import requests
import base64
import time
from typing import List, Dict, Optional
import json

logger = logging.getLogger(__name__)


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
        self._public_api = None

    def _get_public_api(self):
        """Lazy-init PolymarketAPI for public endpoints (events, markets, crypto)."""
        if self._public_api is None:
            from src.market.api import PolymarketAPI

            self._public_api = PolymarketAPI()
        return self._public_api

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
                logger.warning(
                    "Error decoding JSON from Polymarket authenticated API: %s", e
                )
                return None
        except requests.RequestException as e:
            logger.warning("Polymarket authenticated API error: %s", e)
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
                    logger.warning("Error decoding JSON from user profile: %s", e)
                    return None
        except requests.RequestException as e:
            logger.warning("Error fetching user profile for %s: %s", address, e)
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
                    logger.warning("Error decoding JSON from user positions: %s", e)
                    return []
        except requests.RequestException as e:
            logger.warning("Error fetching user positions for %s: %s", address, e)
        return []

    def get_user_trades(
        self, address: str, limit: int = 100, after: int = None
    ) -> List[dict]:
        """Get user's trade history. Optionally filter to trades after Unix timestamp."""
        url = f"https://data-api.polymarket.com/trades?user={address}&limit={limit}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    trades = resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    logger.warning("Error decoding JSON from user trades: %s", e)
                    return []
                if not trades or after is None:
                    return trades or []
                # Filter client-side to recent trades only
                from datetime import datetime

                result = []
                for t in trades:
                    ts = (
                        t.get("timestamp")
                        or t.get("matchTime")
                        or t.get("match_time")
                        or t.get("createdAt")
                    )
                    if ts is None:
                        continue
                    try:
                        if isinstance(ts, (int, float)):
                            t_val = float(ts)
                        elif isinstance(ts, str):
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            t_val = dt.timestamp()
                        else:
                            continue
                        if t_val >= after:
                            result.append(t)
                    except (ValueError, TypeError):
                        continue
                return result
        except requests.RequestException as e:
            logger.warning("Error fetching user trades for %s: %s", address, e)
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
                    logger.warning("Error decoding JSON from user activity: %s", e)
                    return []
        except requests.RequestException as e:
            logger.warning("Error fetching user activity for %s: %s", address, e)
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

    def get_wallet_trades(
        self, address: str, limit: int = 100, after: int = None
    ) -> List[Dict]:
        """Get trade history for a wallet. Optionally filter to trades after Unix timestamp."""
        return self.get_user_trades(address, limit, after)

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
            logger.warning("Error fetching Polymarket leaderboard: %s", e)
        return []

    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get market details. Delegates to public API (handles condition_id via CLOB)."""
        return self._get_public_api().get_market(market_id)

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
            logger.warning("Error fetching markets: %s", e)
        return []

    def get_active_markets(self, limit: int = 500, order: str = "volume") -> List[Dict]:
        """Get active markets. Delegates to public API for order/volume support."""
        return self._get_public_api().get_active_markets(limit=limit, order=order)

    def get_crypto_short_term_markets(self, limit: int = 100) -> List[Dict]:
        """Get crypto 5M/15M/hourly markets. Delegates to public API."""
        return self._get_public_api().get_crypto_short_term_markets(limit=limit)

    def get_sports_markets_from_events(self, limit: int = 200) -> List[Dict]:
        """Get sports markets via events tag. Delegates to public API."""
        return self._get_public_api().get_sports_markets_from_events(limit=limit)

    def get_events(
        self,
        limit: int = 50,
        active: bool = True,
        order: str = None,
        tag_id: str = None,
        slug_contains: str = None,
    ) -> List[Dict]:
        """Get events. Delegates to public API."""
        return self._get_public_api().get_events(
            limit=limit,
            active=active,
            order=order,
            tag_id=tag_id,
            slug_contains=slug_contains,
        )

    def get_event_markets(self, event_id: str) -> List[Dict]:
        """Get markets for an event. Delegates to public API."""
        return self._get_public_api().get_event_markets(event_id)

    def get_market_trades(self, market_id: str, limit: int = 100) -> List[Dict]:
        """Get trades for a market. Delegates to public API."""
        return self._get_public_api().get_market_trades(market_id, limit=limit)

    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """Get full market details. Delegates to public API."""
        return self._get_public_api().get_market_details(market_id)

    def get_market_spread(self, token_id: str) -> Optional[float]:
        """Get market spread. Delegates to public API."""
        return self._get_public_api().get_market_spread(token_id)

    def get_wallet_positions(self, address: str) -> List[Dict]:
        """Get current positions for a wallet."""
        return self.get_user_positions(address)

    def get_wallet_trades(
        self, address: str, limit: int = 100, after: int = None
    ) -> List[Dict]:
        """Get trade history for a wallet. Optionally filter to trades after Unix timestamp."""
        return self.get_user_trades(address, limit, after)

    def get_closed_positions(
        self, address: str, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Get closed positions for a wallet (uses public API)."""
        return self._get_public_api().get_closed_positions(address, limit, offset)

    def close(self):
        """Close the session."""
        self.session.close()
