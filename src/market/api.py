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
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds, doubles each retry


from src.market.polymarket_clob import PolymarketCLOB


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
        """Make rate-limited GET request with retry logic and optional caching."""
        cache_key = f"{url}:{str(params)}"

        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        last_error = None
        for attempt in range(MAX_RETRIES):
            self.rate_limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    retry_after = int(
                        resp.headers.get("Retry-After", RETRY_BACKOFF * (2**attempt))
                    )
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(min(retry_after, 30))
                        continue
                    print(
                        f"[API] Rate limited (429) after {MAX_RETRIES} attempts: {url}"
                    )
                    return None
                if resp.status_code == 422:
                    # Gamma API returns 422 for /markets/{conditionId} - not a retryable error
                    return None
                if resp.status_code in (502, 503, 504):
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF * (2**attempt))
                        continue
                    print(
                        f"[API] Server error ({resp.status_code}) after retries: {url}"
                    )
                    return None
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
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue
                print(f"Error fetching {url}: {e}")
                return None
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

    def get_wallet_trades(
        self, address: str, limit: int = 100, after: int = None
    ) -> List[Dict]:
        """Get trade history for a wallet. Optionally filter to trades after Unix timestamp."""
        url = f"{DATA_API}/trades"
        trades = self._get_list(url, {"user": address, "limit": limit})
        if not trades or after is None:
            return trades or []
        # Filter client-side (Data API may not support 'after' param)
        cutoff = after
        result = []
        for t in trades:
            ts = t.get("timestamp") or t.get("matchTime") or t.get("match_time") or t.get("createdAt")
            if ts is None:
                continue
            try:
                if isinstance(ts, (int, float)):
                    t_val = float(ts)
                elif isinstance(ts, str):
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    t_val = dt.timestamp()
                else:
                    continue
                if t_val >= cutoff:
                    result.append(t)
            except (ValueError, TypeError):
                continue
        return result

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

    def get_events(
        self,
        limit: int = 50,
        active: bool = True,
        order: str = None,
        tag_id: str = None,
        slug_contains: str = None,
    ) -> List[Dict]:
        """Get events from Polymarket. slug_contains finds crypto 5M/15M (e.g. '5m')."""
        url = f"{GAMMA_API}/events"
        params = {"limit": limit}
        if active:
            params["closed"] = "false"
        if order:
            params["order"] = order
            params["ascending"] = "false"
        if tag_id:
            params["tag_id"] = tag_id
        if slug_contains:
            params["slug_contains"] = slug_contains
        return self._get_list(url, params, use_cache=True)

    def get_event_markets(self, event_id: str) -> List[Dict]:
        """Get markets for a specific event."""
        url = f"{GAMMA_API}/markets"
        return self._get_list(url, {"eventId": event_id}, use_cache=True)

    def _is_condition_id(self, s: str) -> bool:
        """True if s looks like a condition ID (0x + 64 hex chars)."""
        if not s or not isinstance(s, str):
            return False
        s = s.strip()
        return s.startswith("0x") and len(s) == 66 and all(c in "0123456789abcdef" for c in s[2:].lower())

    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get a specific market by ID. Gamma API uses slug; condition IDs need CLOB fallback."""
        if not market_id:
            return None
        market_id = str(market_id).strip()

        # Gamma API: /markets/{conditionId} returns 422. CLOB API supports condition_id.
        if self._is_condition_id(market_id):
            try:
                clob = PolymarketCLOB()
                m = clob.get_market(market_id)
                if m:
                    # Normalize CLOB response to Gamma-like dict for callers
                    q = m.get("question") or m.get("market_slug") or "Unknown"
                    return {
                        "id": m.get("id") or market_id,
                        "conditionId": market_id,
                        "question": q,
                        "slug": m.get("slug") or m.get("market_slug"),
                        "volume": m.get("volume", 0),
                        "outcomePrices": m.get("outcome_prices") or m.get("outcomePrices") or "[]",
                    }
            except Exception as e:
                print(f"[API] get_market (condition_id) CLOB: {e}")
            return None

        # Slug or numeric ID: Gamma path /markets/slug/{slug} or /markets/{id}
        url = f"{GAMMA_API}/markets/{market_id}"
        result = self._get(url, use_cache=True)
        if result:
            return result
        # Try slug path format (Gamma docs: /markets/slug/{slug})
        url = f"{GAMMA_API}/markets/slug/{market_id}"
        return self._get(url, use_cache=True)

    def get_markets(
        self,
        limit: int = 100,
        active: bool = True,
        order: str = None,
        tag_id: str = None,
    ) -> List[Dict]:
        """Get markets with optional filtering. order: volume, liquidity, start_date, end_date."""
        url = f"{GAMMA_API}/markets"
        params = {"limit": limit}
        if active:
            params["closed"] = "false"
        if order:
            params["order"] = order
            params["ascending"] = "false"
        if tag_id:
            params["tag_id"] = tag_id
        return self._get_list(url, params, use_cache=True)

    def get_markets_by_tag(self, tag_id: str, limit: int = 100) -> List[Dict]:
        """Get markets filtered by Polymarket tag_id."""
        return self.get_markets(limit=limit, active=True, tag_id=tag_id)

    def get_sports_markets_from_events(self, limit: int = 200) -> List[Dict]:
        """Get sports markets via /sports tag. Tag 1 = sports/competitive (from Polymarket /sports API).
        Extracts markets from events, fallback to keyword filter if empty."""
        events = (
            self.get_events(limit=100, active=True, order="volume", tag_id="1") or []
        )
        result = []
        seen = set()
        for ev in events:
            ev_slug = ev.get("slug") or ev.get("eventSlug")
            for m in ev.get("markets") or []:
                mid = m.get("conditionId") or m.get("id")
                if mid and mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                m = dict(m)
                m["id"] = mid or m.get("conditionId")
                if ev_slug and not m.get("slug"):
                    m["slug"] = ev_slug
                    m["eventSlug"] = ev_slug
                result.append(m)
                if len(result) >= limit:
                    return result
        return result

    def get_crypto_short_term_markets(self, limit: int = 100) -> List[Dict]:
        """Get crypto 5M/15M/hourly markets. Falls back to top crypto when strict filter yields 0."""
        timeframe_kw = [
            "5 min",
            "15 min",
            "5m",
            "15m",
            "hourly",
            "up or down",
            "intraday",
            "rolling",
            "candle",
            "close",
            "open",
            "utc",
            "11:50",
            "11:55",
            "minute",
        ]

        def _extract(events: List, strict: bool = True) -> List[Dict]:
            result = []
            seen = set()
            for ev in events or []:
                ev_slug = ev.get("slug") or ev.get("eventSlug")
                for m in ev.get("markets") or []:
                    mid = m.get("conditionId") or m.get("id")
                    if mid and mid in seen:
                        continue
                    if mid:
                        seen.add(mid)
                    q = (m.get("question", "") or "").lower()
                    if strict and not any(kw in q for kw in timeframe_kw):
                        continue
                    if not strict and not any(
                        k in q
                        for k in [
                            "bitcoin",
                            "btc ",
                            "ethereum",
                            "solana",
                            "crypto",
                            "megaeth",
                        ]
                    ):
                        continue
                    m = dict(m)
                    m["id"] = mid or m.get("conditionId")
                    if ev_slug and not m.get("slug"):
                        m["slug"] = ev_slug
                        m["eventSlug"] = ev_slug
                    result.append(m)
                    if len(result) >= limit:
                        return result
            return result

        # Crypto tag 744 - strict 5M/15M first
        for tag_id in ("744", "1256", None):
            events = self.get_events(limit=200, active=True, tag_id=tag_id) or []
            result = _extract(events, strict=True)
            if result:
                return result

        # Markets endpoint
        result = []
        for m in self.get_markets(limit=500, active=True) or []:
            q = (m.get("question", "") or "").lower()
            if any(kw in q for kw in timeframe_kw):
                result.append(m)
                if len(result) >= limit:
                    return result
        if result:
            return result

        # Fallback: top crypto when no 5M/15M found (API may not expose them)
        events = self.get_events(limit=200, active=True, tag_id="744") or []
        fallback = _extract(events, strict=False)
        if fallback:
            return fallback
        # Last resort: markets with crypto keywords (avoid "sol" in "soliciting")
        result = []
        crypto_kw = ["bitcoin", "btc ", "ethereum", "solana", " crypto", "megaeth"]
        for m in self.get_markets(limit=500, active=True) or []:
            q = (m.get("question", "") or "").lower()
            if any(k in q for k in crypto_kw):
                result.append(m)
                if len(result) >= limit:
                    break
        return result

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

    def get_active_markets(self, limit: int = 500, order: str = "volume") -> List[Dict]:
        """Get currently active markets with key info. Ordered by volume by default for better sports/crypto coverage."""
        markets = self.get_markets(limit=limit, active=True, order=order)
        if not markets and order:
            markets = self.get_markets(limit=limit, active=True)
        return [
            {
                "id": m.get("id") or m.get("conditionId"),
                "conditionId": m.get("conditionId"),
                "slug": m.get("slug") or m.get("eventSlug"),
                "question": m.get("question", "Unknown"),
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
                "category": m.get("category"),
                "outcomePrices": m.get("outcomePrices", "[]"),
                "createdAt": m.get("createdAt"),
                "endDate": m.get("endDate") or m.get("end_date"),
                "groupItemTitle": m.get("groupItemTitle"),
                "clobTokenIds": m.get("clobTokenIds"),
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

    def get_market_spread(self, token_id: str) -> Optional[float]:
        """Get spread (ask - bid) for a token. Returns None if unavailable."""
        if not token_id:
            return None
        try:
            url = f"{CLOB_API}/spread"
            data = self._get(url, {"token_id": token_id})
            if data and "spread" in data:
                return float(data["spread"])
        except Exception as e:
            print(f"[API] get_market_spread error: {e}")
        return None


from src.config import Config
from src.market.auth_api import AuthenticatedPolymarketAPI
from src.market.hashdive import HashdiveClient
from src.market.jupiter import JupiterClient
from src.market.jupiter_prediction import JupiterPredictionAPI
from src.market.jupiter_price import JupiterPriceAPI
from src.market.jupiter_portfolio import JupiterPortfolioAPI
from src.market.jupiter_trigger import JupiterTriggerAPI
from src.market.jupiter_recurring import JupiterRecurringAPI
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
        self._jupiter_price_client = None
        self._jupiter_portfolio_client = None
        self._jupiter_trigger_client = None
        self._jupiter_recurring_client = None
        self._predictfolio_client = None
        self._polyscope_client = None
        self._clob_client = None
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

    def get_clob_client(self) -> PolymarketCLOB:
        """Get a singleton instance of the PolymarketCLOB client."""
        if self._clob_client is None:
            self._clob_client = PolymarketCLOB()
            self.clients.append(self._clob_client)
        return self._clob_client

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

    def get_jupiter_price_client(self) -> JupiterPriceAPI:
        """Get a singleton instance of the JupiterPriceAPI."""
        if self._jupiter_price_client is None:
            self._jupiter_price_client = JupiterPriceAPI()
            self.clients.append(self._jupiter_price_client)
        return self._jupiter_price_client

    def get_jupiter_portfolio_client(self) -> JupiterPortfolioAPI:
        """Get a singleton instance of the JupiterPortfolioAPI."""
        if self._jupiter_portfolio_client is None:
            self._jupiter_portfolio_client = JupiterPortfolioAPI()
            self.clients.append(self._jupiter_portfolio_client)
        return self._jupiter_portfolio_client

    def get_jupiter_trigger_client(self) -> JupiterTriggerAPI:
        """Get a singleton instance of the JupiterTriggerAPI."""
        if self._jupiter_trigger_client is None:
            self._jupiter_trigger_client = JupiterTriggerAPI()
            self.clients.append(self._jupiter_trigger_client)
        return self._jupiter_trigger_client

    def get_jupiter_recurring_client(self) -> JupiterRecurringAPI:
        """Get a singleton instance of the JupiterRecurringAPI."""
        if self._jupiter_recurring_client is None:
            self._jupiter_recurring_client = JupiterRecurringAPI()
            self.clients.append(self._jupiter_recurring_client)
        return self._jupiter_recurring_client
