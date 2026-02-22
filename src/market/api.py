"""Polymarket API client for PolySuite."""

import requests
import time
from typing import List, Dict, Optional, Any
from datetime import datetime
from functools import lru_cache


# API Base URLs
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Rate limiting
MIN_REQUEST_INTERVAL = 0.1  # 100ms between requests


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL):
        self.min_interval = min_interval
        self.last_request = 0

    def wait(self):
        """Wait if necessary to respect rate limit."""
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()


class Cache:
    """Simple in-memory cache with TTL."""

    def __init__(self, ttl: int = 60):
        self.ttl = ttl
        self.cache = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            del self.cache[key]
        return None

    def set(self, key: str, value: Any):
        """Set cached value."""
        self.cache[key] = (value, time.time())

    def clear(self):
        """Clear all cache."""
        self.cache.clear()


class PolymarketAPI:
    """Client for Polymarket API integration."""

    def __init__(self, cache_ttl: int = 10):
        """Initialize API client."""
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )
        self.rate_limiter = RateLimiter()
        self.cache = Cache(ttl=cache_ttl)

    def close(self):
        """Close the session."""
        self.session.close()

    def _get(
        self, url: str, params: Dict = None, use_cache: bool = False
    ) -> Optional[Dict]:
        """Make rate-limited GET request with optional caching."""
        cache_key = f"{url}:{str(params)}"

        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        self.rate_limiter.wait()

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            try:
                data = resp.json()
            except requests.exceptions.JSONDecodeError as e:
                print(f"Error decoding JSON from Polymarket API: {e}")
                return None

            if use_cache:
                self.cache.set(cache_key, data)

            return data
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None

    def _get_list(self, url: str, params: Dict = None, use_cache: bool = False) -> List:
        """Make rate-limited GET request for list response."""
        result = self._get(url, params, use_cache)
        return result if isinstance(result, list) else []

    # ============ WALLET METHODS ============

    def get_wallet_activity(self, address: str, limit: int = 100) -> List[Dict]:
        """Get trading activity for a wallet."""
        url = f"{DATA_API}/activity"
        return self._get_list(url, {"user": address, "limit": limit})

    def get_wallet_positions(self, address: str) -> List[Dict]:
        """Get current positions for a wallet."""
        url = f"{DATA_API}/positions"
        return self._get_list(url, {"user": address})

    def get_wallet_trades(self, address: str, limit: int = 100) -> List[Dict]:
        """Get trade history for a wallet."""
        url = f"{DATA_API}/trades"
        return self._get_list(url, {"user": address, "limit": limit})

    def get_wallet_markets(self, address: str) -> List[str]:
        """Get list of market IDs a wallet has traded in."""
        trades = self.get_wallet_trades(address, limit=500)
        markets = set()
        for trade in trades:
            market_id = trade.get("conditionId") or trade.get("market")
            if market_id:
                markets.add(market_id)
        return list(markets)

    def get_leaderboard(self, limit: int = 50) -> List[Dict]:
        """Get top traders from Polymarket."""
        try:
            url = f"{GAMMA_API}/leaderboards"
            result = self._get(url, {"limit": limit})
            if result and isinstance(result, list):
                return result
        except Exception as e:
            print(f"Error fetching Polymarket leaderboard: {e}")
        return []

    # ============ MARKET METHODS ============

    def get_events(self, limit: int = 50, active: bool = True) -> List[Dict]:
        """Get events from Polymarket."""
        url = f"{GAMMA_API}/events"
        params = {"limit": limit}
        if active:
            params["closed"] = "false"
        return self._get_list(url, params, use_cache=True)

    def get_event_markets(self, event_id: str) -> List[Dict]:
        """Get markets for a specific event."""
        url = f"{GAMMA_API}/markets"
        return self._get_list(url, {"eventId": event_id}, use_cache=True)

    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get a specific market by ID."""
        url = f"{GAMMA_API}/markets/{market_id}"
        return self._get(url, use_cache=True)

    def get_markets(self, limit: int = 100, active: bool = True) -> List[Dict]:
        """Get markets with optional filtering."""
        url = f"{GAMMA_API}/markets"
        params = {"limit": limit}
        if active:
            params["closed"] = "false"
        return self._get_list(url, params, use_cache=True)

    def get_market_trades(self, market_id: str, limit: int = 100) -> List[Dict]:
        """Get all trades for a specific market."""
        url = f"{DATA_API}/trades"
        return self._get_list(
            url, {"market": market_id, "limit": limit}, use_cache=True
        )

    def get_market_wallets(self, market_id: str, limit: int = 100) -> List[str]:
        """Get unique wallet addresses that traded in a market."""
        trades = self.get_market_trades(market_id, limit=limit)
        wallets = set()
        for trade in trades:
            addr = trade.get("address") or trade.get("user")
            if addr:
                wallets.add(addr)
        return list(wallets)

    def get_active_markets(self, limit: int = 100) -> List[Dict]:
        """Get currently active markets with key info."""
        markets = self.get_markets(limit=limit, active=True)
        return [
            {
                "id": m.get("id") or m.get("conditionId"),
                "question": m.get("question", "Unknown"),
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
                "category": m.get("category"),
                "outcomePrices": m.get("outcomePrices", "[]"),
                "active": True,
            }
            for m in markets
        ]

    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """Get full market details."""
        market = self.get_market(market_id)
        if not market:
            return None

        return {
            "id": market.get("id") or market.get("conditionId"),
            "question": market.get("question", "Unknown"),
            "description": market.get("description", ""),
            "category": market.get("category"),
            "volume": market.get("volume", 0),
            "liquidity": market.get("liquidity", 0),
            "outcomes": market.get("outcomes", []),
            "outcomePrices": market.get("outcomePrices", "[]"),
            "closed": market.get("closed", False),
            "resolved": market.get("resolved", False),
            "winner": market.get("winner"),
            "startDate": market.get("startDate"),
            "endDate": market.get("endDate"),
            "createdAt": market.get("createdAt"),
        }

    # ============ PRICE METHODS ============

    def get_token_price(self, token_id: str) -> Optional[float]:
        """Get current price for a token."""
        url = f"{CLOB_API}/price"
        data = self._get(url, {"token_id": token_id})
        if data:
            return float(data.get("price", 0))
        return None


from src.config import Config
from src.market.auth_api import AuthenticatedPolymarketAPI
from src.market.hashdive import HashdiveClient
from src.market.jupiter import JupiterClient
from src.market.jupiter_prediction import JupiterPredictionAPI
from src.market.predictfolio import PredictFolioClient
from src.market.polyscope import PolyScopeClient


class APIClientFactory:
    """Factory for creating API clients."""

    def __init__(self, config: Config):
        self.config = config
        self._polymarket_api = None
        self._hashdive_client = None
        self._jupiter_client = None
        self._jupiter_prediction_client = None
        self._predictfolio_client = None
        self._polyscope_client = None
        self.clients = []

    def close(self):
        """Close all created client sessions."""
        for client in self.clients:
            if hasattr(client, "close"):
                client.close()
        self.clients.clear()

    def get_polymarket_api(self) -> PolymarketAPI:
        """Get a singleton instance of the PolymarketAPI, authenticated if possible."""
        if self._polymarket_api is None:
            if (
                self.config.polymarket_api_key
                and self.config.polymarket_api_secret
                and self.config.polymarket_api_passphrase
            ):
                self._polymarket_api = AuthenticatedPolymarketAPI(
                    self.config.polymarket_api_key,
                    self.config.polymarket_api_secret,
                    self.config.polymarket_api_passphrase,
                )
            else:
                self._polymarket_api = PolymarketAPI()
            self.clients.append(self._polymarket_api)
        return self._polymarket_api

    def get_hashdive_client(self) -> HashdiveClient:
        """Get a singleton instance of the HashdiveClient."""
        if self._hashdive_client is None:
            self._hashdive_client = HashdiveClient(self.config.hashdive_api_key)
            self.clients.append(self._hashdive_client)
        return self._hashdive_client

    def get_jupiter_client(self) -> JupiterClient:
        """Get a singleton instance of the JupiterClient."""
        if self._jupiter_client is None:
            self._jupiter_client = JupiterClient()
            self.clients.append(self._jupiter_client)
        return self._jupiter_client

    def get_predictfolio_client(self) -> PredictFolioClient:
        """Get a singleton instance of the PredictFolioClient."""
        if self._predictfolio_client is None:
            self._predictfolio_client = PredictFolioClient()
            self.clients.append(self._predictfolio_client)
        return self._predictfolio_client

    def get_polyscope_client(self) -> PolyScopeClient:
        """Get a singleton instance of the PolyScopeClient."""
        if self._polyscope_client is None:
            self._polyscope_client = PolyScopeClient()
            self.clients.append(self._polyscope_client)
        return self._polyscope_client

    def get_jupiter_prediction_client(
        self, provider: str = "polymarket"
    ) -> JupiterPredictionAPI:
        """Get a singleton instance of the JupiterPredictionAPI.

        Args:
            provider: Data provider - "polymarket" (on Solana) or "kalshi"
        """
        if self._jupiter_prediction_client is None:
            self._jupiter_prediction_client = JupiterPredictionAPI()
            self.clients.append(self._jupiter_prediction_client)
        return self._jupiter_prediction_client
