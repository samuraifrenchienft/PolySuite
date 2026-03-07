"""Multi-market aggregator for prediction markets.

Combines:
- Polymarket (public API)
- Kalshi (public API - no auth needed)
- Jupiter Prediction (all categories; crypto splits into general + short-term niche)
"""

import requests
import json
import time
import re
import os
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
            # College sports
            "cfb",
            "college football",
            "college basketball",
            "college baseball",
            "ncaa",
            "march madness",
            "final four",
            "college world series",
            "cws",
            "sec",
            "big ten",
            "acc",
            "big 12",
            "alabama",
            "georgia",
            "ohio state",
            "michigan",
            "texas",
            "lsu",
            "clemson",
            "notre dame",
            "duke",
            "kansas",
            "kentucky",
            "gonzaga",
            "villanova",
            "vanderbilt",
            "oregon state",
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
        "weather": [
            "earthquake",
            "hurricane",
            "tornado",
            "weather",
            "storm",
            "flood",
            "blizzard",
            "climate",
            "temperature",
            "forecast",
            "el nino",
            "la nina",
            "cyclone",
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
        "esports": [
            "esports",
            "esport",
            "league of legends",
            "lol",
            "valorant",
            "csgo",
            "cs2",
            "counter-strike",
            "dota",
            "dota 2",
            "overwatch",
            "fortnite",
            "apex legends",
            "call of duty",
            "twitch",
            "steam",
            "pgl",
            "esl",
            "worlds",
            "msi",
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
        "Coronavirus": "weather",
        "Science": "weather",
        "Chess": "esports",
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
        # Optional tuning via env for combo allocation in final selection.
        try:
            self.kalshi_combo_allocation_pct = max(
                0.0,
                min(0.5, float(os.getenv("KALSHI_COMBO_ALLOCATION_PCT", "0.2"))),
            )
        except Exception:
            self.kalshi_combo_allocation_pct = 0.2
        try:
            self.kalshi_combo_min_volume = float(
                os.getenv("KALSHI_COMBO_MIN_VOLUME", "100")
            )
        except Exception:
            self.kalshi_combo_min_volume = 100.0

    def _get_cached(self, key: str) -> Optional[List]:
        if key in self._cache:
            data, timestamp = self._cache[key]
            ttl = 30 if key in ("kalshi", "jupiter") else self._cache_ttl
            if time.time() - timestamp < ttl:
                return data
        return None

    def _set_cached(self, key: str, data: List):
        self._cache[key] = (data, time.time())

    def _is_crypto_short_term(self, event_title: str, market_title: str) -> bool:
        """Return True only for BTC/ETH/SOL 5m/15m up/down style markets."""
        text = f"{event_title} {market_title}".lower()
        has_timeframe = any(
            kw in text for kw in ("5m", "15m", "5 minute", "15 minute", "5-minute", "15-minute")
        )
        has_major_asset = bool(
            re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol)\b", text)
        )
        has_direction = any(kw in text for kw in ("up", "down", "higher", "lower"))
        return has_timeframe and has_major_asset and has_direction

    def _classify_jupiter_category(
        self, requested_category: str, event_title: str, market_title: str
    ) -> str:
        """Split Jupiter crypto into general and short-term niche labels."""
        if requested_category == "crypto" and self._is_crypto_short_term(
            event_title, market_title
        ):
            return "crypto_short_term"
        if requested_category:
            return requested_category
        return self._classify(f"{event_title} {market_title}")

    def _classify(self, question: str) -> str:
        """Classify market category using word boundaries."""
        q = " " + question.lower() + " "  # Add spaces for boundary matching
        for cat, keywords in self.CATEGORIES.items():
            for kw in keywords:
                # Match whole word only
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, q):
                    return cat
        return "other"

    def _is_kalshi_combo_market(self, title: str, ticker: str) -> bool:
        """Detect Kalshi combo/parlay-style contracts."""
        t = str(ticker or "").upper()
        q = str(title or "").lower()
        if "CROSSCATEGORY" in t or "MULTIGAME" in t:
            return True
        # Heuristic: many yes/no legs joined in one title.
        leg_tokens = q.count("yes ") + q.count("no ")
        return leg_tokens >= 3

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
                except (ValueError, TypeError, json.JSONDecodeError):
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

        markets = []
        # Primary path: fetch active events, then fetch markets per event ticker.
        # This avoids combo/parlay-heavy global market feeds.
        try:
            event_resp = self.session.get(
                "https://api.elections.kalshi.com/trade-api/v2/events",
                params={"limit": max(30, int(limit or 100)), "status": "open"},
                timeout=15,
            )
            if event_resp.status_code == 200:
                event_data = event_resp.json()
                events = event_data.get("events", [])
                seen_tickers = set()
                for ev in events:
                    event_ticker = ev.get("event_ticker")
                    if not event_ticker:
                        continue
                    try:
                        m_resp = self.session.get(
                            "https://api.elections.kalshi.com/trade-api/v2/markets",
                            params={
                                "event_ticker": event_ticker,
                                "status": "open",
                                "limit": 20,
                            },
                            timeout=10,
                        )
                        if m_resp.status_code != 200:
                            continue
                        payload = m_resp.json()
                        event_markets = payload.get("markets", [])
                        for m in event_markets:
                            t = str(m.get("ticker") or "")
                            if not t or t in seen_tickers:
                                continue
                            seen_tickers.add(t)
                            # Preserve event category hints for better classification downstream.
                            if ev.get("category") and not m.get("category"):
                                m["category"] = ev.get("category")
                            markets.append(m)
                        if len(markets) >= max(limit * 3, 100):
                            break
                    except Exception:
                        continue
        except Exception as e:
            print(f"[Kalshi] event-based fetch error: {e}")

        # Fallback to global endpoint if event path returns nothing.
        if not markets:
            fetch_limit = max(int(limit or 100) * 5, 200)
            endpoints = [
                (
                    "https://api.elections.kalshi.com/trade-api/v2/markets",
                    {"limit": fetch_limit, "status": "open"},
                ),
                (
                    "https://api.kalshi.com/trade-api/v2/markets",
                    {"limit": fetch_limit, "status": "open"},
                ),
            ]
            for url, params in endpoints:
                try:
                    resp = self.session.get(url, params=params, timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        markets = data.get("markets", data.get("market", []))
                        if isinstance(markets, dict):
                            markets = [markets]
                        if markets:
                            break
                except Exception as e:
                    print(f"[Kalshi] {url}: {e}")
                    continue
        else:
            # Enrich with combo/parlay contracts from global feed so combo strategy can run.
            try:
                combo_resp = self.session.get(
                    "https://api.elections.kalshi.com/trade-api/v2/markets",
                    params={"limit": max(200, int(limit or 100) * 5), "status": "open"},
                    timeout=15,
                )
                if combo_resp.status_code == 200:
                    combo_payload = combo_resp.json()
                    combo_markets = combo_payload.get("markets", [])
                    seen = {str(m.get("ticker") or "") for m in markets}
                    for m in combo_markets:
                        t = str(m.get("ticker") or "")
                        if not t or t in seen:
                            continue
                        if not self._is_kalshi_combo_market(
                            m.get("title", m.get("question", "")), t
                        ):
                            continue
                        seen.add(t)
                        markets.append(m)
            except Exception:
                pass

        if not markets:
            print("[Kalshi] No markets from any endpoint")
            return []

        try:
            alerts = []
            for m in markets:
                title = m.get("title", m.get("question", ""))
                ticker = m.get("ticker", "")
                ticker_upper = str(ticker).upper()

                is_combo = self._is_kalshi_combo_market(title, ticker_upper)

                # Use last_price/yes_ask from list if available (avoid N+1 requests)
                yes_price = m.get("last_price") or m.get("yes_ask") or m.get("yes_bid")
                if yes_price is None:
                    try:
                        price_resp = self.session.get(
                            f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                            timeout=5,
                        )
                        if price_resp.status_code == 200:
                            market_data = price_resp.json()
                            yes_price = market_data.get("yes_ask") or market_data.get(
                                "last_price", 0.5
                            )
                        else:
                            yes_price = 0.5
                    except Exception:
                        yes_price = 0.5
                try:
                    yes_price = float(yes_price) if yes_price is not None else 0.5
                except (ValueError, TypeError):
                    yes_price = 0.5

                # Determine category
                category = "other"
                title_lower = title.lower()
                category_hint = str(m.get("category", "") or "").lower()
                if category_hint:
                    if "sport" in category_hint:
                        category = "sports"
                    elif "crypto" in category_hint:
                        category = "crypto"
                    elif "politic" in category_hint or "election" in category_hint:
                        category = "politics"
                    elif "econ" in category_hint or "world" in category_hint:
                        category = "economy"
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
                    for k in [
                        "game",
                        "match",
                        "win",
                        "score",
                        "nfl",
                        "nba",
                        "sport",
                        "cfb",
                        "college football",
                        "college basketball",
                        "college baseball",
                        "march madness",
                        "final four",
                        "ncaa",
                        "sec",
                        "big ten",
                    ]
                ):
                    category = "sports"
                elif any(
                    k in title_lower
                    for k in ["president", "election", "trump", "biden", "political"]
                ):
                    category = "politics"
                if is_combo:
                    category = f"{category}_combo" if category != "other" else "combo"

                # Kalshi often reports 0 in `volume`; use best available activity proxy.
                vol = float(
                    m.get("volume")
                    or m.get("volume_24h")
                    or m.get("open_interest")
                    or m.get("open_interest_fp")
                    or m.get("notional_value")
                    or m.get("liquidity")
                    or 0
                )
                alerts.append(
                    MarketAlert(
                        source="kalshi",
                        category=category,
                        question=title,
                        price=yes_price,
                        volume=vol,
                        created_at=m.get("created_time", ""),
                        url=f"https://kalshi.com/markets/{ticker}"
                        if ticker
                        else "https://kalshi.com/markets",
                    )
                )

            # Ensure highest-activity markets are surfaced first while reserving
            # a small lane for combo/parlay contracts (strategy-specific monitoring).
            alerts.sort(key=lambda a: float(a.volume or 0), reverse=True)
            combo_alerts = [
                a
                for a in alerts
                if "combo" in str(getattr(a, "category", "")).lower()
                and float(getattr(a, "volume", 0) or 0) >= self.kalshi_combo_min_volume
            ]
            single_alerts = [
                a
                for a in alerts
                if "combo" not in str(getattr(a, "category", "")).lower()
            ]
            combo_slots = min(
                max(1, int(limit * self.kalshi_combo_allocation_pct)),
                len(combo_alerts),
            )
            chosen = single_alerts[: max(0, limit - combo_slots)] + combo_alerts[
                :combo_slots
            ]
            chosen.sort(key=lambda a: float(a.volume or 0), reverse=True)
            alerts = chosen[:limit]
            self._set_cached("kalshi", alerts)
            return alerts

        except Exception as e:
            print(f"[Kalshi] Error: {e}")
            return []

    # ========== JUPITER ==========
    def get_jupiter_markets(self, category: str = None) -> List[MarketAlert]:
        """Get markets from Jupiter Prediction API."""
        cached = self._get_cached("jupiter")
        if cached:
            return cached

        alerts = []
        categories = (
            [category] if category else ["crypto", "sports", "politics", "world"]
        )

        for cat in categories:
            try:
                resp = self.session.get(
                    "https://prediction-market-api.jup.ag/api/v1/events/suggested",
                    params={"category": cat, "provider": "polymarket"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    if resp.status_code == 403:
                        print(
                            "[Jupiter] 403 - API may be geo-restricted (US/SK blocked)"
                        )
                    continue

                data = resp.json()
                for e in data.get("data", []):
                    ev_title = e.get("metadata", {}).get("title", "")
                    for m in e.get("markets", []):
                        if m.get("status") != "open":
                            continue
                        market_title = m.get("metadata", {}).get("title", "")
                        market_id = m.get("marketId", "")
                        # Price from pricing.buyYesPriceUsd (in cents, 0-100000 = 0-100%)
                        pricing = m.get("pricing", {}) or {}
                        buy_yes = pricing.get("buyYesPriceUsd")
                        if buy_yes is not None:
                            price = float(buy_yes) / 100000.0  # 81000 -> 0.81
                        else:
                            result = m.get("result")
                            price = (
                                0.99
                                if result == "yes"
                                else (0.01 if result == "no" else 0.5)
                            )
                        # Skip resolved markets (price >= 99% or <= 1%)
                        if price >= 0.99 or price <= 0.01:
                            continue
                        vol = float(pricing.get("volume", 0) or 0)
                        category_label = self._classify_jupiter_category(
                            cat, ev_title, market_title
                        )

                        alerts.append(
                            MarketAlert(
                                source="jupiter",
                                category=category_label,
                                question=f"{ev_title}: {market_title}"
                                if ev_title
                                else market_title,
                                price=min(1.0, max(0.0, price)),
                                volume=vol,
                                created_at="",
                                url=f"https://jup.ag/prediction/{market_id}"
                                if market_id
                                else "https://jup.ag/prediction",
                            )
                        )
            except Exception as e:
                print(f"[Jupiter] Error: {e}")
                continue

        if not alerts:
            # Fallback: try events endpoint without category
            try:
                resp = self.session.get(
                    "https://prediction-market-api.jup.ag/api/v1/events",
                    params={"limit": 20},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for e in data.get("data", data.get("events", [])):
                        ev_title = e.get("metadata", {}).get("title", "")
                        for m in e.get("markets", []):
                            if m.get("status") != "open":
                                continue
                            market_title = m.get("metadata", {}).get("title", "")
                            market_id = m.get("marketId", "")
                            pricing = m.get("pricing", {}) or {}
                            buy_yes = pricing.get("buyYesPriceUsd")
                            price = (
                                float(buy_yes) / 100000.0
                                if buy_yes is not None
                                else 0.5
                            )
                            if price >= 0.99 or price <= 0.01:
                                continue
                            vol = float(pricing.get("volume", 0) or 0)
                            category_label = self._classify_jupiter_category(
                                "", ev_title, market_title
                            )
                            alerts.append(
                                MarketAlert(
                                    source="jupiter",
                                    category=category_label,
                                    question=f"{ev_title}: {market_title}"
                                    if ev_title
                                    else market_title,
                                    price=min(1.0, max(0.0, price)),
                                    volume=vol,
                                    created_at="",
                                    url=f"https://jup.ag/prediction/{market_id}"
                                    if market_id
                                    else "https://jup.ag/prediction",
                                )
                            )
            except Exception as e:
                print(f"[Jupiter] Fallback: {e}")
            if not alerts:
                print("[Jupiter] No markets (may be geo-restricted)")

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
        except Exception:
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
        except Exception:
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
        except Exception:
            pass

        return providers


# Singleton
aggregator = MarketAggregator()
