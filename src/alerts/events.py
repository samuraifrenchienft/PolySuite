"""Event-based alerts for PolySuite."""

import json
from collections import OrderedDict
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from src.market.api import APIClientFactory


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
        self._previous_prices_crypto = _BoundedDict(maxsize=50)  # coin_id -> {price, change}
        self._previous_volumes = _BoundedDict(maxsize=500)

    def check_new_markets(self, limit: int = 20) -> List[Dict]:
        """Find newly created markets."""
        markets = self.api.get_active_markets(limit=limit) or []
        new_markets = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=self.new_market_hours)

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
                    new_markets.append(m)
            except Exception:
                pass

        new_markets.sort(key=lambda x: x.get("hours_old", 999))
        return new_markets

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
            prices = json.loads(raw_prices) if isinstance(raw_prices, str) else (raw_prices or [])

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
            except Exception:
                pass

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

    def check_new_events(self, hours: int = 1, limit: int = 50) -> List[Dict]:
        """Find newly created events/markets within specified hours."""
        markets = self.api.get_active_markets(limit=limit) or []
        new_events = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)

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
                    new_events.append(m)
            except Exception:
                pass

        new_events.sort(key=lambda x: x.get("hours_old", 999))
        return new_events

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
            # Get active markets
            markets = self.api.get_active_markets(limit=100) or []

            # Filter to crypto-related markets
            crypto_keywords = [
                "bitcoin",
                "btc",
                "ethereum",
                "eth",
                "solana",
                "sol",
                "crypto",
                "dogecoin",
                "xrp",
                "cardano",
            ]

            for m in markets:
                q = m.get("question", "").lower()
                if not any(kw in q for kw in crypto_keywords):
                    continue

                # Get current price
                raw_prices = m.get("outcomePrices")
                prices = json.loads(raw_prices) if isinstance(raw_prices, str) else (raw_prices or [])
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
            pass

        return moves

    def check_crypto_prices(self) -> List[Dict]:
        """Check real crypto prices using CoinGecko API."""
        import requests

        coins = [
            "bitcoin",
            "ethereum",
            "solana",
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
            pass

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
                "china",
                "europe",
                "economy",
                "federal reserve",
                "treasury",
                "dollar",
                "currency",
                "forex",
            ],
            "science": [
                "science",
                "research",
                "discovery",
                "nasa",
                "space",
                "mars",
                "moon",
                "climate",
                "weather",
                "storm",
                "hurricane",
                "tornado",
                "earthquake",
                "volcano",
                "cure",
                "medical",
                "health",
                "pandemic",
                "vaccine",
                "drug",
                "fda",
            ],
            "weather": [
                "weather",
                "storm",
                "hurricane",
                "tornado",
                "flood",
                "snow",
                "winter",
                "summer",
                "heat wave",
                "cold wave",
                "el nino",
                "la nina",
                "temperature",
                "climate",
                "global warming",
                "forecast",
                "tropical",
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
                "solana",
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
        except Exception:
            return {cat: [] for cat in categories}
