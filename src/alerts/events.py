"""Event-based alerts for PolySuite."""

import json
import logging
import re
from collections import OrderedDict
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from src.market.api import APIClientFactory

logger = logging.getLogger(__name__)


class _BoundedDict(OrderedDict):
    """Dict with max size; evicts oldest when full."""

    def __init__(self, *args, maxsize: int = 500, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        if key not in self and len(self) >= self.maxsize:
            self.popitem(last=False)
        super().__setitem__(key, value)


class EventAlerter:
    """Detect interesting events in prediction markets."""

    def __init__(
        self,
        api_factory: APIClientFactory,
        new_market_hours: int = 6,
        volume_spike_multiplier: float = 2.0,
        odds_move_threshold: float = 0.15,
    ):
        """Initialize event alerter.

        Args:
            api_factory: API client factory
            new_market_hours: Alert for markets created within this window
            volume_spike_multiplier: Alert if volume > avg * this
            odds_move_threshold: Alert if odds moved by this much
        """
        self.api = api_factory.get_polymarket_api()
        self.new_market_hours = new_market_hours
        self.volume_spike_multiplier = volume_spike_multiplier
        self.odds_move_threshold = odds_move_threshold
        self._previous_prices = _BoundedDict(maxsize=500)  # market_id -> {yes, no}
        self._previous_prices_crypto = _BoundedDict(
            maxsize=50
        )  # coin_id -> {price, change}
        self._previous_volumes = _BoundedDict(maxsize=500)
        self.CATEGORY_KEYWORDS = self._load_category_keywords()

    def _load_category_keywords(self) -> Dict[str, List[str]]:
        """Load category keywords from JSON file."""
        try:
            with open("src/alerts/category_keywords.json", "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("Error loading category keywords: %s", e)
            return {}

    CRYPTO_SHORT_TERM_KEYWORDS = [
        "5 min",
        "15 min",
        "5m",
        "15m",
        "5-minute",
        "15-minute",
        "5 minute",
        "15 minute",
        "hourly",
        "up or down",
        "higher",
        "lower",
        "up",
        "down",
    ]

    def is_crypto_short_term(self, question: str) -> bool:
        """Check if question describes a crypto 5M/15M short-term market."""
        if not question:
            return False
        q = question.lower()
        has_timeframe = any(kw in q for kw in self.CRYPTO_SHORT_TERM_KEYWORDS)
        has_asset = bool(
            re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol)\b", q)
        )
        has_direction = any(
            kw in q for kw in ("up", "down", "higher", "lower", "above", "below")
        )
        return has_timeframe and has_asset and has_direction

    def get_category(self, question: str, group_title: str = "") -> Optional[str]:
        """Determine market category from question and optional group title."""
        q = (question or "").lower()
        group = (group_title or "").lower()
        q = q + " " + group
        if self.is_crypto_short_term(q):
            return "crypto"

        # Check sports FIRST - avoid false positives from crypto
        sports_keywords = self.CATEGORY_KEYWORDS.get("sports", [])
        for kw in sports_keywords:
            # Disambiguate sports-team words that can appear in crypto contexts.
            if kw == "magic" and any(
                sig in q for sig in ("magic coin", "magic crypto", "$magic")
            ):
                continue
            if kw == "jaguar" and "jaguar coin" in q:
                continue
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "sports"

        # Strong crypto identifiers should win before broad politics/economy terms.
        if re.search(
            r"\b(bitcoin|btc|ethereum|eth|solana|avax|xrp|dogecoin|doge|cardano|ada|chainlink|toncoin|injective|polkadot)\b",
            q,
        ):
            return "crypto"

        # Check politics
        politics_keywords = self.CATEGORY_KEYWORDS.get("politics", [])
        for kw in politics_keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "politics"

        # Check economy (US revenue, tariffs, etc)
        economy_keywords = self.CATEGORY_KEYWORDS.get("economy", [])
        for kw in economy_keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "economy"

        # Check weather
        weather_keywords = self.CATEGORY_KEYWORDS.get("weather", [])
        for kw in weather_keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "weather"

        # Check esports
        esports_keywords = self.CATEGORY_KEYWORDS.get("esports", [])
        for kw in esports_keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "esports"

        # Check crypto LAST - more specific
        crypto_keywords = self.CATEGORY_KEYWORDS.get("crypto", [])

        # Special handling for sports teams that share names with cryptos
        sports_team_crypto = {
            "avalanche": ["avax", "avalanche protocol"],
            "magic": ["magic coin", "magic crypto"],
            "jaguar": ["jaguar coin"],
        }
        ambiguous_crypto_tokens = {
            "link": ("chainlink", "$link", "link token"),
            "base": ("coinbase", "base chain", "base network", "base l2"),
            "ton": ("toncoin", "the open network"),
            "op": ("optimism", "op token"),
            "inj": ("injective", "inj token"),
            "sol": ("solana", "$sol"),
        }

        for kw in crypto_keywords:
            # Skip single words that might be sports teams unless it's clearly crypto
            if kw in ["avalanche", "magic", "jaguar"]:
                # Check if this is the crypto version
                if kw == "avalanche" and "avax" in q.lower():
                    return "crypto"
                continue
            if kw in ambiguous_crypto_tokens:
                if any(sig in q for sig in ambiguous_crypto_tokens[kw]):
                    return "crypto"
                continue
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "crypto"

        return "other"

    def filter_by_category(
        self, markets: List[Dict], categories: List[str]
    ) -> List[Dict]:
        """Filter markets by category."""
        if not categories:
            return markets
        return [
            m for m in markets
            if self.get_category(m.get("question", ""), m.get("groupItemTitle", "")) in categories
        ]

    def check_new_markets(
        self, limit: int = 20, categories: List[str] = None, hours: int = None
    ) -> List[Dict]:
        """Find newly created markets."""
        markets = self.api.get_active_markets(limit=limit) or []

        # Apply category filter
        if categories:
            markets = self.filter_by_category(markets, categories)

        new_markets = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours or self.new_market_hours)

        for m in markets:
            created_at = m.get("createdAt") or m.get("created_at")
            if not created_at:
                continue

            try:
                if isinstance(created_at, str):
                    if created_at.endswith("Z"):
                        created_at = created_at[:-1] + "+00:00"
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                else:
                    created = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)

                if created > cutoff:
                    m["hours_old"] = (now - created).total_seconds() / 3600
                    m["category"] = self.get_category(m.get("question", ""), m.get("groupItemTitle", ""))
                    new_markets.append(m)
            except (ValueError, TypeError) as e:
                logger.debug("Error parsing date: %s", e)

        new_markets.sort(key=lambda x: x.get("hours_old", 999))
        return new_markets

    def fetch_markets_for_categories(self, limit: int = 500) -> Dict[str, List[Dict]]:
        """Fetch markets once and return crypto, sports, politics + all_market_ids for cleanup.
        Sports: merge tag-based fetch (Polymarket /sports) with keyword filter for better coverage."""
        markets = self.api.get_active_markets(limit=limit) or []
        crypto = self.filter_by_category(markets, ["crypto"])
        politics = self.filter_by_category(markets, ["politics"])
        sports_from_active = self.filter_by_category(markets, ["sports"])

        # Sports: also fetch via events API (tag 1 = sports) - often has more sports than top 500 by volume
        sports = list(sports_from_active)
        seen_sports = {m.get("id") or m.get("conditionId") for m in sports if m}
        if hasattr(self.api, "get_sports_markets_from_events"):
            try:
                tag_sports = self.api.get_sports_markets_from_events(limit=200) or []
                for m in tag_sports:
                    mid = m.get("id") or m.get("conditionId")
                    if mid and mid not in seen_sports:
                        seen_sports.add(mid)
                        sports.append(m)
            except Exception as e:
                logger.warning("Error fetching sports markets from events: %s", e)

        all_ids = {m.get("id") or m.get("conditionId") for m in markets if m}
        for m in sports:
            mid = m.get("id") or m.get("conditionId")
            if mid:
                all_ids.add(mid)

        return {
            "crypto": crypto,
            "sports": sports,
            "politics": politics,
            "all_market_ids": all_ids,
        }

    def _fetch_and_filter_markets(self, category: str, limit: int, markets: List[Dict] = None) -> List[Dict]:
        """Fetch and filter markets by category."""
        if markets is not None:
            return self.filter_by_category(markets, [category])
        
        if category == "sports" and hasattr(self.api, "get_sports_markets_from_events"):
            tag_markets = self.api.get_sports_markets_from_events(limit=limit) or []
            if tag_markets:
                return self.filter_by_category(tag_markets, ["sports"])

        m = self.api.get_active_markets(limit=limit) or []
        return self.filter_by_category(m, [category])

    def check_crypto_markets(
        self, limit: int = 200, markets: List[Dict] = None
    ) -> List[Dict]:
        """Get only crypto-related markets. Pass pre-fetched markets to avoid extra API call."""
        return self._fetch_and_filter_markets("crypto", limit, markets)

    def check_crypto_short_term_markets(self, limit: int = 100) -> List[Dict]:
        """Fetch crypto 5M/15M/hourly markets ordered by volume, enriched for alerts."""
        try:
            markets = self.api.get_crypto_short_term_markets(limit=limit) or []
        except Exception as e:
            logger.warning("Error fetching crypto short term markets: %s", e)
            markets = []
        enriched = []
        for m in markets:
            raw_prices = m.get("outcomePrices")
            prices = (
                json.loads(raw_prices)
                if isinstance(raw_prices, str)
                else (raw_prices or [])
            )
            m = dict(m)
            if prices and len(prices) >= 2:
                try:
                    m["yes_pct"] = float(prices[0])
                    m["no_pct"] = (
                        float(prices[1]) if len(prices) > 1 else 1 - float(prices[0])
                    )
                except (ValueError, TypeError):
                    pass
            m["is_crypto_short_term"] = True
            enriched.append(m)
        return enriched

    def check_sports_markets(
        self, limit: int = 400, markets: List[Dict] = None
    ) -> List[Dict]:
        """Get sports markets. Pass pre-fetched markets to avoid extra API call."""
        return self._fetch_and_filter_markets("sports", limit, markets)

    def check_politics_markets(
        self, limit: int = 400, markets: List[Dict] = None
    ) -> List[Dict]:
        """Get only politics-related markets. Pass pre-fetched markets to avoid extra API call."""
        return self._fetch_and_filter_markets("politics", limit, markets)

    def check_volume_spikes(self, limit: int = 30) -> List[Dict]:
        """Find markets with unusual volume."""
        markets = self.api.get_active_markets(limit=limit) or []
        spikes = []

        for m in markets:
            market_id = m.get("id")
            try:
                volume = float(m.get("volume", 0) or 0)
            except (ValueError, TypeError):
                volume = 0

            if not market_id or volume < 1000:
                continue

            prev_volume = self._previous_volumes.get(market_id, 0)
            if prev_volume > 0:
                ratio = volume / prev_volume
                if ratio >= self.volume_spike_multiplier:
                    m["volume_ratio"] = ratio
                    m["volume_increase"] = volume - prev_volume
                    spikes.append(m)

            self._previous_volumes[market_id] = volume

        spikes.sort(key=lambda x: x.get("volume_ratio", 0), reverse=True)
        return spikes

    def check_odds_movements(self, limit: int = 30) -> List[Dict]:
        """Find markets with big odds movements."""
        markets = self.api.get_active_markets(limit=limit) or []
        movements = []

        for m in markets:
            market_id = m.get("id")
            raw_prices = m.get("outcomePrices")
            prices = (
                json.loads(raw_prices)
                if isinstance(raw_prices, str)
                else (raw_prices or [])
            )

            if not market_id or not prices:
                continue

            try:
                if not prices or len(prices) < 2:
                    continue

                current_yes = float(prices[0])
                prev = self._previous_prices.get(market_id, {})

                if prev:
                    prev_yes = prev.get("yes", 0.5)
                    if prev_yes > 0:
                        change = abs(current_yes - prev_yes)
                        if change >= self.odds_move_threshold:
                            m["odds_change"] = change
                            m["prev_yes"] = prev_yes
                            m["current_yes"] = current_yes
                            movements.append(m)

                self._previous_prices[market_id] = {
                    "yes": current_yes,
                    "timestamp": datetime.now(timezone.utc),
                }
            except (ValueError, TypeError) as e:
                logger.debug("Error parsing date in expiring events: %s", e)

        movements.sort(key=lambda x: x.get("odds_change", 0), reverse=True)
        return movements

    def check_all(self) -> Dict[str, List[Dict]]:
        """Run all event checks and return results."""
        return {
            "new_markets": self.check_new_markets(),
            "volume_spikes": self.check_volume_spikes(),
            "odds_movements": self.check_odds_movements(),
        }

    def get_summary(self) -> str:
        """Get text summary of all events."""
        events = self.check_all()

        lines = []

        new = events.get("new_markets", [])
        if new:
            lines.append(f"### New Markets ({len(new)})")
            for m in new[:3]:
                lines.append(
                    f"- {m.get('question', '')[:50]} ({m.get('hours_old', 0):.1f}h old)"
                )
            lines.append("")

        spikes = events.get("volume_spikes", [])
        if spikes:
            lines.append(f"### Volume Spikes ({len(spikes)})")
            for m in spikes[:3]:
                lines.append(
                    f"- {m.get('question', '')[:50]} ({m.get('volume_ratio', 0):.1f}x)"
                )
            lines.append("")

        moves = events.get("odds_movements", [])
        if moves:
            lines.append(f"### Odds Movements ({len(moves)})")
            for m in moves[:3]:
                lines.append(
                    f"- {m.get('question', '')[:50]} ({m.get('odds_change', 0):.0%} move)"
                )

        if not lines:
            return "No significant events detected."

        return "\n".join(lines)



    def check_expiring_events(self, hours: int = 2, limit: int = 20) -> List[Dict]:
        """Find events ending soon (sports games, etc)."""
        markets = self.api.get_active_markets(limit=limit) or []
        expiring = []
        now = datetime.now(timezone.utc)

        for m in markets:
            end_date = m.get("endDate") or m.get("end_date") or m.get("end_date_iso")
            if not end_date:
                continue

            try:
                if isinstance(end_date, str):
                    if end_date.endswith("Z"):
                        end_date = end_date[:-1] + "+00:00"
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.fromtimestamp(end_date / 1000, tz=timezone.utc)

                hours_left = (end_dt - now).total_seconds() / 3600
                if 0 < hours_left <= hours:
                    m["hours_left"] = hours_left
                    # Enrich with event/game context
                    m["event_title"] = m.get("groupItemTitle") or ""
                    # Market consensus from outcomePrices (YES %)
                    raw_prices = m.get("outcomePrices")
                    prices = (
                        json.loads(raw_prices)
                        if isinstance(raw_prices, str)
                        else (raw_prices or [])
                    )
                    if prices and len(prices) >= 2:
                        try:
                            yes_pct = float(prices[0])
                            m["yes_pct"] = yes_pct
                            m["no_pct"] = (
                                float(prices[1]) if len(prices) > 1 else 1 - yes_pct
                            )
                        except (ValueError, TypeError):
                            pass
                    expiring.append(m)
            except Exception:
                pass

        expiring.sort(key=lambda x: x.get("hours_left", 999))
        return expiring

    def check_crypto_moves(self, tracked: List[str] = None) -> List[Dict]:
        """Check for significant crypto price movements in Polymarket markets."""
        if tracked is None:
            tracked = ["BTC", "ETH", "SOL", "Bitcoin", "Ethereum", "Solana"]

        moves = []

        try:
            # Get active markets - fetch more for better coverage
            markets = self.api.get_active_markets(limit=200) or []

            # Use proper category filtering
            crypto_markets = self.filter_by_category(markets, ["crypto"])

            for m in crypto_markets:
                q = m.get("question", "")

                # Get current price
                raw_prices = m.get("outcomePrices")
                if not raw_prices:
                    continue

                prices = (
                    json.loads(raw_prices)
                    if isinstance(raw_prices, str)
                    else (raw_prices or [])
                )
                if not prices or len(prices) < 2:
                    continue

                try:
                    yes_price = (
                        float(prices[0])
                        if isinstance(prices[0], (int, float))
                        else float(prices[0].strip('"'))
                    )
                except Exception:
                    continue

                # Compare to previous price stored in memory
                market_id = m.get("id")
                if market_id in self._previous_prices:
                    prev = self._previous_prices[market_id].get("yes", 0.5)
                    if prev > 0:
                        change = abs(yes_price - prev) / prev
                        # Alert if > 3% move
                        if change >= 0.03:
                            direction = "up" if yes_price > prev else "down"
                            moves.append(
                                {
                                    "symbol": "CRYPTO",
                                    "question": m.get("question", ""),
                                    "price": yes_price,
                                    "move_pct": change * 100,
                                    "direction": direction,
                                    "timeframe": "POLY",
                                    "market_id": market_id,
                                }
                            )

                # Store current price
                self._previous_prices[market_id] = {
                    "yes": yes_price,
                    "timestamp": datetime.now(timezone.utc),
                }

        except Exception as e:
            logger.warning("check_crypto_moves error: %s", e)

        return moves

    def check_crypto_prices(self) -> List[Dict]:
        """Check real crypto prices using CoinGecko API."""
        import requests

        coins = [
            "bitcoin",
            "ethereum",
            "dogecoin",
            "cardano",
            "ripple",
            "polkadot",
            "avalanche-2",
            "chainlink",
            "uniswap",
        ]
        moves = []

        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": ",".join(coins),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()

                for coin_id, info in data.items():
                    current_price = info.get("usd", 0)
                    change_24h = info.get("usd_24h_change", 0)

                    # Store and compare (use separate dict to avoid collision with market IDs)
                    if coin_id not in self._previous_prices_crypto:
                        self._previous_prices_crypto[coin_id] = {
                            "price": current_price,
                            "change": change_24h,
                        }
                        continue

                    prev = self._previous_prices_crypto[coin_id]
                    prev_price = prev.get("price", 0)

                    if prev_price > 0:
                        # Detect significant intraday moves
                        price_change = abs(current_price - prev_price) / prev_price

                        # Alert on 3%+ intraday moves OR big 24h moves
                        if price_change >= 0.03 or abs(change_24h) >= 5:
                            direction = "up" if current_price > prev_price else "down"
                            moves.append(
                                {
                                    "symbol": coin_id.upper(),
                                    "price": current_price,
                                    "move_pct": price_change * 100
                                    if price_change >= 0.03
                                    else change_24h,
                                    "direction": direction,
                                    "timeframe": "5m"
                                    if price_change >= 0.03
                                    else "24h",
                                    "change_24h": change_24h,
                                }
                            )

                    # Update stored price
                    self._previous_prices_crypto[coin_id] = {
                        "price": current_price,
                        "change": change_24h,
                    }

        except Exception as e:
            logger.warning("Error fetching crypto prices: %s", e)

        return moves

    def check_market_categories(self) -> Dict[str, List[Dict]]:
        """Check for new/trending markets by category."""
        categories = {
            "sports": [
                "nfl",
                "nba",
                "mlb",
                "nhl",
                "soccer",
                "football",
                "boxing",
                "mma",
                "ufc",
                "tennis",
                "golf",
                "olympics",
                "world cup",
                "espn",
                "f1",
                "racing",
                "nascar",
                "indianapolis 500",
                "wimbledon",
                "us open",
            ],
            "tech": [
                "ai",
                "google",
                "meta",
                "facebook",
                "apple",
                "amazon",
                "microsoft",
                "openai",
                "nvidia",
                "tesla",
                "spacex",
                "tech",
                "bitcoin",
                "ether",
                "twitter",
                "x.com",
                "meta",
                "amazon",
                "netflix",
                "apple",
                "nvidia",
                "amd",
                "intel",
                "cybersecurity",
                "robotics",
                "quantum",
            ],
            "stocks": [
                "stock",
                "s&p",
                "dow",
                "nasdaq",
                "wall st",
                "fed",
                "sec",
                "ipo",
                "earnings",
                "market",
                "treasury",
                "bond",
                "yield",
                "recession",
                "inflation",
                "economy",
            ],
            "business": [
                "business",
                "company",
                "ceo",
                "merger",
                "acquisition",
                "ipo",
                "revenue",
                "profit",
                "layoff",
                "bankrupt",
                "startup",
                "funding",
                "valuation",
                "fortune 500",
            ],
            "economics": [
                "economy",
                "gdp",
                "inflation",
                "recession",
                "fed",
                "interest rate",
                "unemployment",
                "jobs",
                "wage",
                "trade",
                "tariff",
                "tariffs",
                "china",
                "europe",
                "economy",
                "federal reserve",
                "treasury",
                "dollar",
                "currency",
                "forex",
            ],
            "weather": [
                "weather",
                "climate",
                "storm",
                "hurricane",
                "tornado",
                "earthquake",
                "volcano",
                "flood",
                "blizzard",
                "temperature",
                "forecast",
                "el nino",
                "la nina",
                "cyclone",
                "tsunami",
            ],
            "pop_culture": [
                "movie",
                "music",
                "celebrity",
                "oscar",
                "grammy",
                "emmy",
                "netflix",
                "drake",
                "kanye",
                "taylor swift",
                "election",
                "trump",
                "biden",
                "politics",
                "government",
                "congress",
                "senate",
                "supreme court",
                "scotus",
                "wwe",
                "aew",
                "wrestling",
                "gaming",
                "esports",
                "streamer",
                "twitch",
                "youtube",
            ],
            "crypto": [
                "bitcoin",
                "btc",
                "ethereum",
                "eth",
                "crypto",
                "token",
                "blockchain",
                "defi",
                "nft",
                "binance",
                "coinbase",
                "exchange",
            ],
        }

        try:
            markets = self.api.get_active_markets(limit=100) or []
            results = {cat: [] for cat in categories}

            for m in markets:
                q = m.get("question", "").lower()
                for cat, keywords in categories.items():
                    if any(kw in q for kw in keywords):
                        m["category"] = cat
                        results[cat].append(m)
                        break

            return results
        except Exception as e:
            logger.warning("Error checking market categories: %s", e)
            return {cat: [] for cat in categories}
