"""Multi-market aggregator for prediction markets.

Combines:
- Polymarket (public API)
- Kalshi (public API - no auth needed)
- Jupiter (requires API key)
"""

import requests
import json
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MarketAlert:
    """Represents a market alert."""

    source: str  # polymarket, kalshi, jupiter
    category: str  # crypto, sports, politics, etc.
    question: str
    price: float
    volume: float
    created_at: str
    url: str


class MarketAggregator:
    """Aggregate markets from multiple prediction market sources."""

    # Alternative API endpoints for each provider
    API_ENDPOINTS = {
        "polymarket": [
            (
                "https://gamma-api.polymarket.com/markets",
                {"active": True, "closed": False, "limit": 200},
            ),
            ("https://clob.polymarket.com/markets", {}),
        ],
        "kalshi": [
            ("https://api.kalshi.com/v1/events", {"status": "active", "limit": 100}),
            (
                "https://demo-api.kalshi.com/v1/events",
                {"status": "active", "limit": 100},
            ),
        ],
        "jupiter": [
            (
                "https://prediction-market-api.jup.ag/api/v1/events/suggested",
                {"category": "crypto", "provider": "polymarket"},
            ),
            ("https://prediction-market-api.jup.ag/api/v1/events", {"limit": 50}),
        ],
    }

    # Track provider failures
    _provider_errors = {}  # {provider: error_count}
    _provider_last_check = {}  # {provider: timestamp}
    _provider_cooldown = 300  # 5 min cooldown after too many errors

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self._cache = {}
        self._cache_ttl = 60

    # Category keywords - matches Polymarket API categories
    CATEGORIES = {
        "crypto": [
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "dogecoin",
            "xrp",
            "cardano",
            "chainlink",
            "ada",
            "crypto",
            "cryptocurrency",
            "defi",
            "token",
        ],
        "sports": [
            "nfl",
            "nba",
            "mlb",
            "nhl",
            "ufc",
            "boxing",
            "mma",
            "soccer",
            "football",
            "basketball",
            "baseball",
            "hockey",
            "tennis",
            "golf",
            "nascar",
            "f1",
            "super bowl",
            "world cup",
            "fifa",
            "stanley cup",
            "playoffs",
            "draft",
            "lakers",
            "celtics",
            "warriors",
            "bulls",
            "heat",
            "mavericks",
            "grizzlies",
            "49ers",
            "packers",
            "eagles",
        ],
        "politics": [
            "president",
            "election",
            "trump",
            "biden",
            "congress",
            "senate",
            "parliament",
            "governor",
            "republican",
            "democrat",
            "voting",
            "political",
            "impeach",
            "inaugurated",
        ],
        "economy": [
            "inflation",
            "gdp",
            "unemployment",
            "fed",
            "interest rate",
            "recession",
            "tariff",
            "natural gas",
            "oil",
            "gold",
        ],
        "science": [
            "covid",
            "coronavirus",
            "vaccine",
            "earthquake",
            "hurricane",
            "weather",
            "climate",
            "science",
            "space",
            "nasa",
        ],
        "business": [
            "market cap",
            "ipo",
            "stock",
            "tesla",
            "apple",
            "amazon",
            "coinbase",
            "google",
            "microsoft",
            "meta",
            "earnings",
        ],
        "entertainment": [
            "grammy",
            "oscar",
            "emmy",
            "movie",
            "netflix",
            "disney",
            "album",
            "chart",
            "billboard",
            "streaming",
        ],
        "chess": [
            "chess",
            "carlsen",
            "nakamura",
            "norway chess",
            "ftx crypto cup",
        ],
    }

    # Polymarket API category mapping
    POLYMARKET_CAT_MAP = {
        "Sports": "sports",
        "NBA Playoffs": "sports",
        "Olympics": "sports",
        "Crypto": "crypto",
        "US-current-affairs": "politics",
        "Global Politics": "politics",
        "Business": "business",
        "Coronavirus": "science",
        "Science": "science",
        "Chess": "chess",
        "NFTs": "other",
        "Art": "other",
        "Poker": "other",
        "Pop-Culture ": "entertainment",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self._cache = {}
        self._cache_ttl = 60  # 1 minute

    def _get_cached(self, key: str) -> Optional[List]:
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: List):
        self._cache[key] = (data, time.time())

    def _classify(self, question: str) -> str:
        """Classify market category using word boundaries."""
        import re

        q = " " + question.lower() + " "  # Add spaces for boundary matching
        for cat, keywords in self.CATEGORIES.items():
            for kw in keywords:
                # Match whole word only
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, q):
                    return cat
        return "other"

    # ========== POLYMARKET ==========
    def get_polymarkets(self, limit: int = 200) -> List[MarketAlert]:
        """Get markets from Polymarket."""
        cached = self._get_cached("polymarket")
        if cached:
            return cached

        try:
            resp = self.session.get(
                "https://gamma-api.polymarket.com/markets",
                params={"active": True, "closed": False, "limit": limit},
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            markets = resp.json()
            alerts = []
            for m in markets:
                q = m.get("question", "")

                # Parse outcomePrices - comes as JSON string
                try:
                    outcome_prices = m.get("outcomePrices")
                    if isinstance(outcome_prices, str):
                        outcome_prices = json.loads(outcome_prices)
                    if outcome_prices and isinstance(outcome_prices, list):
                        price = float(outcome_prices[0])
                    else:
                        price = 0.5
                except:
                    price = 0.5

                alerts.append(
                    MarketAlert(
                        source="polymarket",
                        category=self._classify(q),
                        question=q,
                        price=price,
                        volume=float(m.get("volume", 0) or 0),
                        created_at=m.get("createdAt", ""),
                        url=f"https://polymarket.com/event/{m.get('slug', '')}",
                    )
                )

            self._set_cached("polymarket", alerts)
            return alerts

        except Exception as e:
            print(f"[Polymarket] Error: {e}")
            return []

    # ========== KALSHI ==========
    def get_kalshi_markets(self, limit: int = 100) -> List[MarketAlert]:
        """Get markets from Kalshi (public API - no auth)."""
        cached = self._get_cached("kalshi")
        if cached:
            return cached

        try:
            # Use the correct endpoint: api.elections.kalshi.com
            resp = self.session.get(
                "https://api.elections.kalshi.com/trade-api/v2/markets",
                params={"limit": limit},
                timeout=15,
            )

            if resp.status_code != 200:
                print(f"[Kalshi] Error: status {resp.status_code}")
                return []

            data = resp.json()
            markets = data.get("markets", [])

            alerts = []
            for m in markets:
                title = m.get("title", m.get("question", ""))
                ticker = m.get("ticker", "")

                # Get current price
                try:
                    price_resp = self.session.get(
                        f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                        timeout=10,
                    )
                    if price_resp.status_code == 200:
                        market_data = price_resp.json()
                        yes_price = market_data.get("yes_ask", 0.5)
                    else:
                        yes_price = 0.5
                except:
                    yes_price = 0.5

                # Determine category
                category = "other"
                title_lower = title.lower()
                if any(
                    k in title_lower
                    for k in [
                        "bitcoin",
                        "eth",
                        "crypto",
                        "inflation",
                        "fed",
                        "rate",
                    ]
                ):
                    category = (
                        "crypto"
                        if any(k in title_lower for k in ["bitcoin", "eth", "crypto"])
                        else "economy"
                    )
                elif any(
                    k in title_lower
                    for k in ["game", "match", "win", "score", "nfl", "nba", "sport"]
                ):
                    category = "sports"
                elif any(
                    k in title_lower
                    for k in ["president", "election", "trump", "biden", "political"]
                ):
                    category = "politics"

                alerts.append(
                    MarketAlert(
                        source="kalshi",
                        category=category,
                        question=title,
                        price=yes_price,
                        volume=float(m.get("volume", 0) or 0),
                        created_at=m.get("created_time", ""),
                        url=f"https://kalshi.com/markets/{ticker}",
                    )
                )

            self._set_cached("kalshi", alerts)
            return alerts

        except Exception as e:
            print(f"[Kalshi] Error: {e}")
            return []

    # ========== JUPITER ==========
    def get_jupiter_markets(self, category: str = None) -> List[MarketAlert]:
        """Get markets from Jupiter Prediction API (free, no auth needed)."""
        cached = self._get_cached("jupiter")
        if cached:
            return cached

        alerts = []
        categories = [category] if category else ["crypto", "sports", "politics"]

        for cat in categories:
            try:
                resp = self.session.get(
                    "https://prediction-market-api.jup.ag/api/v1/events/suggested",
                    params={"category": cat, "provider": "polymarket"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                for e in data.get("data", []):
                    title = e.get("metadata", {}).get("title", "")
                    for m in e.get("markets", []):
                        market_title = m.get("metadata", {}).get("title", "")
                        # Determine price from result
                        result = m.get("result", "N/A")
                        if result == "yes":
                            price = 0.99
                        elif result == "no":
                            price = 0.01
                        else:
                            price = 0.5

                        alerts.append(
                            MarketAlert(
                                source="jupiter",
                                category=cat,
                                question=f"{title}: {market_title}",
                                price=price,
                                volume=0,  # Not provided by this API
                                created_at="",
                                url=f"https://jup.ag/prediction/{m.get('marketId', '')}",
                            )
                        )
            except Exception as e:
                print(f"[Jupiter] Error: {e}")
                continue

        self._set_cached("jupiter", alerts)
        return alerts

    # ========== COMBINED ==========
    def get_all_markets(self) -> Dict[str, List[MarketAlert]]:
        """Get all markets from all sources."""
        return {
            "polymarket": self.get_polymarkets(),
            "kalshi": self.get_kalshi_markets(),
            "jupiter": self.get_jupiter_markets(),
        }

    def get_by_category(self, category: str) -> List[MarketAlert]:
        """Get all markets in a specific category."""
        all_markets = []
        for source, markets in self.get_all_markets().items():
            all_markets.extend([m for m in markets if m.category == category])
        return all_markets

    # ========== AUTO-DISCOVERY ==========
    def get_active_providers(self) -> List[str]:
        """Check which providers are working and return active ones."""
        providers = []

        # Test Polymarket
        try:
            resp = self.session.get(
                "https://gamma-api.polymarket.com/markets",
                params={"active": True, "closed": False, "limit": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                providers.append("polymarket")
        except:
            pass

        # Test Kalshi
        try:
            resp = self.session.get(
                "https://api.kalshi.com/v1/events",
                params={"status": "active", "limit": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                providers.append("kalshi")
        except:
            pass

        # Test Jupiter
        try:
            resp = self.session.get(
                "https://prediction-market-api.jup.ag/api/v1/events/suggested",
                params={"category": "crypto", "provider": "polymarket"},
                timeout=10,
            )
            if resp.status_code == 200:
                providers.append("jupiter")
        except:
            pass

        return providers


# Singleton
aggregator = MarketAggregator()
