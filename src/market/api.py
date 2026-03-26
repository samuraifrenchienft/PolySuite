"""Polymarket API client for PolySuite."""

import json
import logging
import requests
import time
from typing import List, Dict, Optional, Any
from datetime import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)


# API Base URLs
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Rate limiting
MIN_REQUEST_INTERVAL = 0.1  # 100ms between requests
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds, doubles each retry


from src.market.polymarket_clob import PolymarketCLOB


_KEYWORD_CATEGORY_MAP = {
    # Sports
    "nba": "sports-nba", "nfl": "sports-nfl", "mlb": "sports-mlb",
    "nhl": "sports-nhl", "soccer": "sports-soccer", "mls": "sports-soccer",
    "epl": "sports-soccer", "ucl": "sports-soccer", "premier league": "sports-soccer",
    "la liga": "sports-soccer", "serie a": "sports-soccer", "bundesliga": "sports-soccer",
    "champions league": "sports-soccer", "world cup": "sports-soccer",
    "ufc": "sports-ufc", "mma": "sports-ufc",
    "f1": "sports-formula1", "formula 1": "sports-formula1", "formula one": "sports-formula1",
    "ncaa": "sports-ncaa", "cfb": "sports-ncaa", "cbb": "sports-ncaa",
    "march madness": "sports-ncaa", "college football": "sports-ncaa",
    "college basketball": "sports-ncaa",
    "golf": "sports-golf", "pga": "sports-golf", "masters tournament": "sports-golf",
    "tennis": "sports-tennis", "wimbledon": "sports-tennis", "us open tennis": "sports-tennis",
    "wta": "sports-tennis", "atp": "sports-tennis", "roland garros": "sports-tennis",
    "australian open": "sports-tennis", "french open": "sports-tennis",
    "miami open": "sports-tennis", "indian wells": "sports-tennis",
    "nascar": "sports", "boxing": "sports", "wnba": "sports",
    "fifa": "sports-soccer", "fif-": "sports-soccer", "copa": "sports-soccer",
    "serie-a": "sports-soccer", "la-liga": "sports-soccer",
    "super bowl": "sports-nfl", "world series": "sports-mlb",
    "stanley cup": "sports-nhl", "nba finals": "sports-nba",
    "spread:": "sports", "moneyline": "sports", " o/u ": "sports", " pts ": "sports",
    # Crypto
    "bitcoin": "crypto", "btc": "crypto", "ethereum": "crypto", "eth ": "crypto",
    "crypto": "crypto", "solana": "crypto", "sol ": "crypto", "dogecoin": "crypto",
    "doge": "crypto", "xrp": "crypto", "cardano": "crypto", "polkadot": "crypto",
    "avalanche": "crypto", "polygon": "crypto", "matic": "crypto", "chainlink": "crypto",
    "defi": "crypto", "nft": "crypto", "stablecoin": "crypto", "altcoin": "crypto",
    "memecoin": "crypto", "token": "crypto", "blockchain": "crypto",
    # Politics
    "trump": "politics", "biden": "politics", "congress": "politics",
    "election": "politics", "senate": "politics", "president": "politics",
    "democrat": "politics", "republican": "politics", "governor": "politics",
    "ballot": "politics", "vote": "politics", "political": "politics",
    "gop": "politics", "dnc": "politics", "rnc": "politics",
    "midterm": "politics", "primary": "politics", "inaugur": "politics",
    "impeach": "politics", "legislation": "politics", "white house": "politics",
    "supreme court": "politics", "cabinet": "politics", "poll": "politics",
    # Entertainment
    "oscar": "entertainment", "emmy": "entertainment", "grammy": "entertainment",
    "box office": "entertainment", "movie": "entertainment", "film ": "entertainment",
    "tv show": "entertainment", "netflix": "entertainment", "disney": "entertainment",
    "spotify": "entertainment", "album": "entertainment", "billboard": "entertainment",
    "celebrity": "entertainment", "hollywood": "entertainment", "streaming": "entertainment",
    "youtube": "entertainment", "tiktok": "entertainment", "reality tv": "entertainment",
    "award show": "entertainment", "music": "entertainment", "rapper": "entertainment",
    "pop star": "entertainment", "actor": "entertainment", "actress": "entertainment",
    # Science / Tech
    "nasa": "science", "spacex": "science", "climate": "science",
    "vaccine": "science", "pandemic": "science", "asteroid": "science",
    "mars": "science", "moon landing": "science", "space": "science",
    "scientific": "science", "research": "science", "ai ": "science",
    "artificial intelligence": "science", "openai": "science", "gpt": "science",
    "quantum": "science", "fusion": "science", "gene": "science",
    # Weather
    "hurricane": "weather", "tornado": "weather", "earthquake": "weather",
    "temperature": "weather", "weather": "weather", "snowfall": "weather",
    "rainfall": "weather", "flood": "weather", "wildfire": "weather",
    "drought": "weather", "storm": "weather", "heat wave": "weather",
    # Economics / Finance
    "fed rate": "economics", "interest rate": "economics", "inflation": "economics",
    "gdp": "economics", "recession": "economics", "stock market": "economics",
    "s&p 500": "economics", "s&p500": "economics", "dow jones": "economics",
    "nasdaq": "economics", "unemployment": "economics", "federal reserve": "economics",
    "treasury": "economics", "trade war": "economics", "tariff": "economics",
    "cpi": "economics", "fomc": "economics", "jobs report": "economics",
    "oil price": "economics", "gas price": "economics", "housing market": "economics",
}


def _category_from_keywords(text: str) -> Optional[str]:
    """Match text against keyword patterns, return category or None."""
    if not text:
        return None
    t = text.lower()
    for keyword, cat in _KEYWORD_CATEGORY_MAP.items():
        if keyword in t:
            return cat
    return None


def extract_market_category(market: Optional[Dict]) -> Optional[str]:
    """Resolve a display category from Gamma-shaped market JSON.

    Polymarket often puts labels on ``category``, but CLOB-only fetches or partial
    payloads may omit it while still having ``events[].category`` or ``tags``.
    Without this, classifiers bucket most trades as \"other\".

    Fallback chain: category field -> events[].category -> tags -> slug keywords
    -> question/title keywords -> description keywords.
    """
    if not market or not isinstance(market, dict):
        return None

    # Priority: slug > question > tags > description > raw category field.
    # Polymarket's "category" field is unreliable — e.g. NBA games tagged "politics".
    # Slugs are machine-generated and always contain the real sport/topic prefix.

    # 1. Slug-based keyword matching (most reliable — "nba-okc-bos-2026-03-25")
    slug = market.get("slug") or market.get("eventSlug") or ""
    cat = _category_from_keywords(slug)
    if cat:
        return cat

    # 2. Question/title keyword matching
    question = market.get("question") or market.get("title") or ""
    cat = _category_from_keywords(question)
    if cat:
        return cat

    # 3. Tags (CLOB returns tags like ["crypto", "bitcoin"] or [{"slug": "..."}])
    tags = market.get("tags")
    if isinstance(tags, list):
        for t in tags:
            tag_text = None
            if isinstance(t, dict):
                tag_text = (t.get("slug") or t.get("label") or "").strip()
            elif isinstance(t, str):
                tag_text = t.strip()
            if tag_text:
                mapped = _category_from_keywords(tag_text)
                if mapped:
                    return mapped
                return tag_text.lower().replace(" ", "-")

    # 4. Description keyword matching
    desc = market.get("description") or ""
    cat = _category_from_keywords(desc)
    if cat:
        return cat

    # 5. Raw category field (least reliable — only use as final fallback)
    _USELESS_CATEGORIES = {"us-current-affairs", "current-affairs", "n/a", "other", "general", ""}
    raw = market.get("category")
    if raw is not None and str(raw).strip().lower() not in _USELESS_CATEGORIES:
        return str(raw).strip().lower()

    # 6. events[].category (same issue as raw category, last resort)
    events = market.get("events") or []
    if isinstance(events, list):
        for ev in events:
            if isinstance(ev, dict):
                ec = ev.get("category")
                if ec is not None and str(ec).strip().lower() not in _USELESS_CATEGORIES:
                    return str(ec).strip().lower()

    return None


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
                    logger.warning(
                        "Rate limited (429) after %d attempts: %s", MAX_RETRIES, url
                    )
                    return None
                if resp.status_code == 422:
                    # Gamma API returns 422 for /markets/{conditionId} - not a retryable error
                    return None
                if resp.status_code in (502, 503, 504):
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF * (2**attempt))
                        continue
                    logger.warning(
                        "Server error (%s) after retries: %s", resp.status_code, url
                    )
                    return None
                resp.raise_for_status()
                try:
                    data = resp.json()
                except requests.exceptions.JSONDecodeError as e:
                    logger.warning("JSON decode error from Polymarket API: %s", e)
                    return None
                if use_cache:
                    self.cache.set(cache_key, data)
                return data
            except requests.RequestException as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue
                logger.warning("Error fetching %s: %s", url, e)
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

    def get_closed_positions(
        self, address: str, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Get closed positions for a wallet with realized PnL.

        Polymarket Data API: /closed-positions returns realizedPnl per position.
        """
        url = f"{DATA_API}/closed-positions"
        params = {
            "user": address,
            "limit": limit,
            "offset": offset,
            "sortBy": "REALIZEDPNL",
            "sortDirection": "DESC",
        }
        return self._get_list(url, params)

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
            logger.warning("Error fetching Polymarket leaderboard: %s", e)
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
        return (
            s.startswith("0x")
            and len(s) == 66
            and all(c in "0123456789abcdef" for c in s[2:].lower())
        )

    def _gamma_market_by_condition_id(self, condition_id: str) -> Optional[Dict]:
        """Gamma returns 422 for GET /markets/{conditionId}; use list filter instead."""
        if not condition_id:
            return None
        url = f"{GAMMA_API}/markets"
        rows = self._get_list(
            url, {"condition_id": condition_id.strip(), "limit": 1}, use_cache=True
        )
        if rows and isinstance(rows[0], dict):
            return rows[0]
        return None

    def _enrich_market_category(self, market: Optional[Dict]) -> Optional[Dict]:
        """Set ``category`` when only nested tags/events have it."""
        if not market or not isinstance(market, dict):
            return market
        if (market.get("category") or "").strip():
            return market
        cat = extract_market_category(market)
        if cat:
            market["category"] = cat
        return market

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
                    closed = bool(m.get("closed", False) or m.get("active") is False)
                    tokens = m.get("tokens") or []
                    winning_outcome = None
                    for t in tokens:
                        if isinstance(t, dict) and t.get("winner"):
                            winning_outcome = (t.get("outcome") or "").strip()
                            break
                    # Fallback: closed market with token price ~1 means winner
                    if not winning_outcome and closed and tokens:
                        for t in tokens:
                            if isinstance(t, dict):
                                p = float(t.get("price", 0) or 0)
                                if p >= 0.95:
                                    winning_outcome = (t.get("outcome") or "").strip()
                                    break
                    # outcomePrices fallback (JSON string or list)
                    if not winning_outcome and closed:
                        raw = m.get("outcome_prices") or m.get("outcomePrices") or "[]"
                        if isinstance(raw, str):
                            try:
                                prices = json.loads(raw)
                            except Exception:
                                prices = []
                        else:
                            prices = list(raw) if raw else []
                        if len(prices) >= 2:
                            p0, p1 = float(prices[0] or 0), float(prices[1] or 0)
                            if p0 >= 0.95 and p1 <= 0.05:
                                winning_outcome = "yes"
                            elif p1 >= 0.95 and p0 <= 0.05:
                                winning_outcome = "no"
                    # Resolved = closed and we know the winner (CLOB; Gamma 422 for condition_id)
                    resolved = bool(closed and winning_outcome)
                    out = {
                        "id": m.get("id") or market_id,
                        "conditionId": market_id,
                        "question": q,
                        "slug": m.get("slug") or m.get("market_slug"),
                        "volume": m.get("volume", 0),
                        "outcomePrices": m.get("outcome_prices")
                        or m.get("outcomePrices")
                        or "[]",
                        "closed": closed,
                        "resolved": resolved,
                        "outcome": winning_outcome or None,
                        "endDate": m.get("end_date_iso") or m.get("endDate") or m.get("end_date"),
                        "tokens": tokens,
                    }
                    # Gamma GET /markets/{conditionId} returns 422; list ?condition_id= works.
                    gamma = self._gamma_market_by_condition_id(market_id)
                    if not gamma:
                        try:
                            g2 = self._get(f"{GAMMA_API}/markets/{market_id}", use_cache=True)
                            gamma = g2 if isinstance(g2, dict) else None
                        except Exception:
                            gamma = None
                    if gamma and isinstance(gamma, dict):
                        if gamma.get("category"):
                            out["category"] = gamma.get("category")
                        if gamma.get("events") is not None:
                            out["events"] = gamma.get("events")
                        if gamma.get("tags") is not None:
                            out["tags"] = gamma.get("tags")
                        if "resolved" in gamma and gamma.get("resolved") is not None:
                            out["resolved"] = gamma.get("resolved")
                        if "closed" in gamma and gamma.get("closed") is not None:
                            out["closed"] = gamma.get("closed")
                        if gamma.get("outcome"):
                            out["outcome"] = gamma.get("outcome")
                    merged = {**out, **(gamma or {})}
                    cat = extract_market_category(merged)
                    if cat:
                        out["category"] = cat
                    else:
                        self._enrich_market_category(out)
                    return out
            except Exception as e:
                logger.debug("get_market (condition_id) CLOB: %s", e)
            return None

        # Slug or numeric ID: Gamma path /markets/slug/{slug} or /markets/{id}
        url = f"{GAMMA_API}/markets/{market_id}"
        result = self._get(url, use_cache=True)
        if not result:
            url = f"{GAMMA_API}/markets/slug/{market_id}"
            result = self._get(url, use_cache=True)
        return self._enrich_market_category(result) if result else None

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
            "5 min", "15 min", "5m", "15m", "5-min", "15-min", "5 minute", "15 minute",
            "hourly", "up or down", "intraday", "rolling", "candle", "close", "open",
            "utc", "11:50", "11:55", "minute", "higher", "lower", "above", "below",
        ]
        crypto_kw = [
            "bitcoin", "btc", "ethereum", "eth", "solana", " sol ", "crypto",
            "megaeth", "dogecoin", "doge", "xrp", "cardano", "ada", "avalanche",
            "avax", "polkadot", " dot ", "matic", "link", "chainlink", "ton", "toncoin",
            "injective", "inj", "sui", "aptos", "apt", "sei", "base", "arb", "arbitrum",
            "op ", "optimism", "bonk", "wif", "pepe", "shib", "floki",
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
                    group = (m.get("groupItemTitle") or "").lower()
                    text = q + " " + group
                    has_timeframe = any(kw in text for kw in timeframe_kw)
                    has_crypto = any(ck in text for ck in crypto_kw)
                    if strict and (not has_timeframe or not has_crypto):
                        continue
                    if not strict and not has_crypto:
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

        # Markets endpoint - MUST have crypto keyword too
        result = []
        for m in self.get_markets(limit=500, active=True) or []:
            q = (m.get("question", "") or "").lower()
            group = (m.get("groupItemTitle") or "").lower()
            text = q + " " + group
            if any(kw in text for kw in timeframe_kw) and any(ck in text for ck in crypto_kw):
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
        # Last resort: markets with crypto keywords (use " sol " to avoid "soliciting")
        result = []
        for m in self.get_markets(limit=500, active=True) or []:
            q = (m.get("question", "") or "").lower()
            group = (m.get("groupItemTitle") or "").lower()
            text = q + " " + group
            if any(k in text for k in crypto_kw):
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
            logger.debug("get_market_spread error: %s", e)
        return None


def get_api() -> "PolymarketAPI":
    """Legacy: return a PolymarketAPI instance for mapper and other callers."""
    return PolymarketAPI()


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
