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

    # Category keywords - comprehensive matching
    # Based on CoinMarketCap top cryptos + prediction market terms
    CATEGORY_KEYWORDS = {
        "crypto": [
            # Top by market cap (2026)
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "ether",
            "tether",
            "usdt",
            "usdc",
            "xrp",
            "bnb",
            "binance",
            "solana",
            "sol",
            "dogecoin",
            "doge",
            "cardano",
            "ada",
            "tron",
            "trx",
            "sui",
            "chainlink",
            "link",
            "avax",
            "avalanche",
            "stellar",
            "xlm",
            "shiba inu",
            "shib",
            "shiba",
            "hedera",
            "hbar",
            "ton",
            "telegram",
            "polkadot",
            "dot",
            "bitcoin cash",
            "bch",
            "uniswap",
            "uni",
            "litecoin",
            "ltc",
            "aave",
            "maker",
            "mkr",
            "cosmos",
            "atom",
            "filecoin",
            "fil",
            "internet computer",
            "icp",
            "render",
            "rndr",
            "optimism",
            "op",
            "arbitrum",
            "arb",
            "base",
            "sei",
            "injective",
            "inj",
            "aptos",
            "apt",
            "synthetix",
            "snx",
            "gmx",
            "pyth",
            "fetch",
            "fet",
            "ai16z",
            "bonk",
            "wif",
            "popcat",
            "goat",
            "fartcoin",
            "vitalik",
            "sbf",
            # DeFi/Crypto terms
            "defi",
            "dao",
            "nft",
            "token",
            "tokenize",
            "cryptocurrency",
            "crypto",
            "altcoin",
            "coinbase",
            "kraken",
            "metamask",
            "phantom",
            "solflare",
            "hyperliquid",
            "hype",
            "megaeth",
            "jupiter",
            "raydium",
            "orca",
            "pump fun",
            "pump",
            "memecoin",
            "meme coin",
            "加密",
            # Crypto 5M/15M short-term
            "5 min",
            "15 min",
            "5m",
            "15m",
            "hourly",
            "up or down",
            "candle",
            "close",
            "open",
            "et",
            "utc",
            "11:50",
            "11:55",
        ],
        "sports": [
            # NFL
            "nfl",
            "super bowl",
            "nfc",
            "afc",
            "falcons",
            "panthers",
            "49ers",
            "packers",
            "eagles",
            "cowboys",
            "ravens",
            "bengals",
            "bills",
            "broncos",
            "browns",
            "buccaneers",
            "cardinals",
            "chargers",
            "chiefs",
            "colts",
            "commanders",
            "cowboys",
            "dolphins",
            "falcons",
            "giants",
            "jaguars",
            "jets",
            "lions",
            "packers",
            "panthers",
            "patriots",
            "raiders",
            "rams",
            "ravens",
            "saints",
            "seahawks",
            "steelers",
            "texans",
            "titans",
            "vikings",
            # NBA
            "nba",
            "nba finals",
            "playoffs",
            "draft",
            "lakers",
            "celtics",
            "warriors",
            "bulls",
            "heat",
            "nets",
            "knicks",
            "mavericks",
            "grizzlies",
            "suns",
            "clippers",
            "nuggets",
            "cavaliers",
            "hornets",
            "pelicans",
            "pistons",
            "raptors",
            "rockets",
            "kings",
            "spurs",
            "jazz",
            "wizards",
            "magic",
            "hawks",
            "thunder",
            "bucks",
            "pacers",
            "blazers",
            # MLB
            "mlb",
            "world series",
            "yankees",
            "dodgers",
            "red sox",
            "baseball",
            "astros",
            "cubs",
            "giants",
            "mets",
            "phillies",
            "cardinals",
            "dodgers",
            "orioles",
            "rangers",
            "rays",
            "reds",
            "brewers",
            "guardians",
            "mariners",
            "marlins",
            "athletics",
            "pirates",
            "padres",
            "white sox",
            "nationals",
            # NHL
            "nhl",
            "stanley cup",
            "hockey",
            "hurricanes",
            "bruins",
            "sabres",
            "flames",
            "ducks",
            "blackhawks",
            "blue jackets",
            "blues",
            "predators",
            "senators",
            "capitals",
            "golden knights",
            "islanders",
            "jets",
            "kraken",
            "lightning",
            "maple leafs",
            "oilers",
            "panthers",
            "penguins",
            "red wings",
            "sharks",
            "stars",
            "wild",
            # Soccer - Premier League
            "premier league",
            "manchester",
            "liverpool",
            "arsenal",
            "chelsea",
            "tottenham",
            "man city",
            "man utd",
            "newcastle",
            "west ham",
            "brighton",
            "aston villa",
            "wolves",
            "fulham",
            "crystal palace",
            # Soccer - La Liga
            "la liga",
            "real madrid",
            "barcelona",
            "atletico madrid",
            "sevilla",
            "villareal",
            "athletic bilbao",
            "real sociedad",
            # Soccer - Champions League
            "champions league",
            "uefa",
            "bayern",
            "psg",
            "juventus",
            "milan",
            "inter milan",
            "dortmund",
            "napoli",
            "roma",
            "leverkusen",
            # Soccer - World Cup/Olympics
            "world cup",
            "fifa",
            "euro",
            "euro 2028",
            "world cup 2026",
            "argentina",
            "brazil",
            "france",
            "germany",
            "spain",
            "england",
            "portugal",
            "netherlands",
            "italy",
            "belgium",
            # Olympics
            "olympics",
            "olympic",
            "paris 2028",
            "los angeles 2028",
            "milan 2026",
            "brisbane 2032",
            # Tennis
            "tennis",
            "wimbledon",
            "us open",
            "french open",
            "australian open",
            "ao",
            "rg",
            "usao",
            "atp",
            "wta",
            "djokovic",
            "alcaraz",
            "sinner",
            "fritz",
            "zverev",
            "medvedev",
            "rune",
            "ruud",
            "tsitsipas",
            # Golf
            "golf",
            "pga",
            "masters",
            "us open",
            "british open",
            "pga championship",
            "liv golf",
            " LIV",
            "ryder cup",
            "seppi",
            "scottie",
            "rory",
            "schauffele",
            # UFC/Boxing/MMA
            "ufc",
            "boxing",
            "mma",
            "wrestling",
            "wwe",
            "one championship",
            "jon jones",
            "jones",
            "mcgregor",
            "poirier",
            "islam",
            # Cricket
            "cricket",
            "ipl",
            "big bash",
            "ashes",
            "world cup t20",
            "india",
            "australia",
            "england",
            "pakistan",
            "south africa",
            # College Football (CFB)
            "cfb",
            "college football",
            "ncaa football",
            "sec",
            "big ten",
            "big 12",
            "acc",
            "pac-12",
            "pac12",
            "alabama",
            "crimson tide",
            "georgia",
            "bulldogs",
            "ohio state",
            "buckeyes",
            "michigan",
            "wolverines",
            "texas",
            "longhorns",
            "oregon",
            "ducks",
            "lsu",
            "tigers",
            "clemson",
            "tigers",
            "notre dame",
            "fighting irish",
            "penn state",
            "nittany lions",
            "tennessee",
            "volunteers",
            "florida",
            "gators",
            "auburn",
            "war eagles",
            "oklahoma",
            "sooners",
            "usc",
            "trojans",
            "ucla",
            "bruins",
            "florida state",
            "seminoles",
            "miami",
            "hurricanes",
            "texas a&m",
            "aggies",
            "ole miss",
            "rebels",
            "arkansas",
            "razorbacks",
            "kentucky",
            "wildcats",
            "south carolina",
            "gamecocks",
            "missouri",
            "tigers",
            "iowa",
            "hawkeyes",
            "wisconsin",
            "badgers",
            "nebraska",
            "cornhuskers",
            "michigan state",
            "spartans",
            "washington",
            "huskies",
            "utah",
            "utes",
            "colorado",
            "buffaloes",
            "baylor",
            "bears",
            "oklahoma state",
            "cowboys",
            "kansas state",
            "wildcats",
            "tcu",
            "horned frogs",
            "west virginia",
            "mountaineers",
            "iowa state",
            "cyclones",
            "north carolina",
            "tar heels",
            "virginia tech",
            "hokies",
            "louisville",
            "cardinals",
            "nc state",
            "wolfpack",
            "syracuse",
            "orange",
            "pitt",
            "panthers",
            "boston college",
            "eagles",
            "wake forest",
            "demon deacons",
            "duke",
            "blue devils",
            "georgia tech",
            "yellow jackets",
            "virginia",
            "cavaliers",
            "miami hurricanes",
            "bowl game",
            "college playoff",
            "cfp",
            # College Basketball
            "college basketball",
            "ncaa basketball",
            "march madness",
            "final four",
            "ncaa tournament",
            "duke blue devils",
            "kansas",
            "jayhawks",
            "kentucky wildcats",
            "north carolina tar heels",
            "ucla bruins",
            "villanova",
            "wildcats",
            "gonzaga",
            "bulldogs",
            "arizona",
            "wildcats",
            "houston",
            "cougars",
            "purdue",
            "boilermakers",
            "uconn",
            "huskies",
            "creighton",
            "bluejays",
            "marquette",
            "golden eagles",
            "tennessee volunteers",
            "alabama crimson tide",
            "arkansas razorbacks",
            "baylor bears",
            "iowa hawkeyes",
            "illinois",
            "fighting illini",
            "michigan state spartans",
            "wisconsin badgers",
            "indiana",
            "hoosiers",
            "maryland",
            "terrapins",
            "ohio state buckeyes",
            "michigan wolverines",
            "penn state nittany lions",
            "syracuse orange",
            "louisville cardinals",
            "virginia cavaliers",
            "florida state seminoles",
            "miami hurricanes",
            "nc state wolfpack",
            "wake forest demon deacons",
            "georgia tech yellow jackets",
            "clemson tigers",
            "virginia tech hokies",
            "texas longhorns",
            "kansas jayhawks",
            "texas tech",
            "red raiders",
            "oklahoma sooners",
            "oklahoma state cowboys",
            "west virginia mountaineers",
            "iowa state cyclones",
            "kansas state wildcats",
            "tcu horned frogs",
            "baylor bears",
            "san diego state",
            "aztecs",
            "st. john's",
            "red storm",
            "georgetown",
            "hoyas",
            "xavier",
            "musketeers",
            "butler",
            "bulldogs",
            "providence",
            "friars",
            "seton hall",
            "pirates",
            "depaul",
            "blue demons",
            # College Baseball
            "college baseball",
            "ncaa baseball",
            "college world series",
            "cws",
            "omaha",
            "sec baseball",
            "acc baseball",
            "big 12 baseball",
            "tennessee volunteers",
            "arkansas razorbacks",
            "lsu tigers",
            "texas a&m aggies",
            "vanderbilt",
            "commodores",
            "florida gators",
            "ole miss rebels",
            "auburn tigers",
            "alabama crimson tide",
            "georgia bulldogs",
            "south carolina gamecocks",
            "kentucky wildcats",
            "mississippi state",
            "bulldogs",
            "clemson tigers",
            "florida state seminoles",
            "north carolina tar heels",
            "virginia cavaliers",
            "duke blue devils",
            "nc state wolfpack",
            "miami hurricanes",
            "louisville cardinals",
            "wake forest demon deacons",
            "georgia tech yellow jackets",
            "boston college eagles",
            "oregon state",
            "beavers",
            "stanford",
            "cardinal",
            "ucla bruins",
            "arizona wildcats",
            "oregon ducks",
            "washington huskies",
            "super regional",
            "regionals",
            # Other Sports
            "f1",
            "formula 1",
            "nascar",
            "indy 500",
            "daytona",
            "nba all star",
            "all star game",
            "mvp",
            "roty",
            # Esports
            "valorant",
            "league of legends",
            "lol",
            "dota",
            "csgo",
            "overwatch",
        ],
        "politics": [
            # US Politics
            "president",
            "election",
            "trump",
            "biden",
            "harris",
            "pence",
            "congress",
            "senate",
            "house",
            "parliament",
            "prime minister",
            "governor",
            "republican",
            "democrat",
            "gop",
            "democratic",
            "voting",
            "vote",
            "ballot",
            "inauguration",
            "nominee",
            "primary",
            "caucus",
            "convention",
            "debate",
            "rally",
            "campaign",
            "white house",
            "capitol",
            "supreme court",
            "scotus",
            "senator",
            "representative",
            "congressman",
            "congresswoman",
            "mayor",
            "attorney general",
            "secretary",
            "ambassador",
            # US Elections 2028
            "2028",
            "hillary",
            "clinton",
            "obama",
            "bush",
            "clinton",
            "tim walz",
            "gavin newsom",
            "j.d. vance",
            "vance",
            "pence",
            "ron desantis",
            "desantis",
            "nikki haley",
            "haley",
            "christie",
            "mayor pete",
            "buttigieg",
            "ramaswamy",
            "vivek",
            "youngkin",
            "beshear",
            "andrew yang",
            "yang",
            "mike pence",
            "mike johnson",
            "marco rubio",
            "rubio",
            "bernie",
            "sanders",
            "aoc",
            "ocasio-cortez",
            "warren",
            "booker",
            "klobuchar",
            "bennet",
            "scaled",
            "whitmer",
            "gregg",
            "shapiro",
            "pritzker",
            "newsom",
            "adams",
            "adams",
            # US Elections 2024/2026
            "2024",
            "2026",
            "2025",
            "hunter biden",
            "impeachment",
            "indictment",
            "supreme court",
            "roe",
            "wade",
            "abortion",
            # International Politics
            "ukraine",
            "russia",
            "putin",
            "zelensky",
            "war",
            "invasion",
            "nato",
            "eu",
            "europe",
            "united nations",
            "security council",
            "china",
            "xi",
            "taiwan",
            "beijing",
            "hong kong",
            "iran",
            "israel",
            "netanyahu",
            "gaza",
            "hamas",
            "hezbollah",
            "north korea",
            "kim jong",
            "putin",
            "biden",
            "trump",
            "brexit",
            "uk",
            "britain",
            "british",
            "european union",
            "canada",
            "mexico",
            "immigration",
            "border",
            "deportation",
            "tariff",
            "tariffs",
            "trade war",
            "sanction",
            "nuclear",
            "weapon",
            # Cabinet / Legislative
            "cabinet",
            "veto",
            "executive order",
            "nomination",
            "confirmation",
            "mcconnell",
            "schumer",
            "pelosi",
            "mccarthy",
            "jeffries",
            "johnson",
            "speaker",
            # Kalshi/Polymarket overlap
            "cfb",
            "kalshi",
            "daily",
            "fed",
            "rate cut",
            "rate hike",
            "fomc",
            # World Leaders
            "macron",
            "le pen",
            "starmer",
            "sunak",
            "meloni",
            "scholz",
            "modi",
            "india",
            "japan",
            "australia",
            "brazil",
            "mexico",
            "erdogan",
            "turkey",
            "saudi",
            "uae",
            "king",
            "queen",
        ],
        "tech": [
            "ai",
            "artificial intelligence",
            "openai",
            "chatgpt",
            "gpt",
            "llm",
            "machine learning",
            "nvidia",
            "meta",
            "earnings",
            "ipo",
            "amd",
            "intel",
            "quantum",
            "cybersecurity",
            "robotics",
            "software",
            "startup",
            "tech",
        ],
        "economy": [
            "inflation",
            "gdp",
            "unemployment",
            "interest rate",
            "fed",
            "recession",
            # Kalshi
            "cfb",
            "cpi",
            "jobs report",
            "tariff",
            "tariffs",
            "revenue",
            "market cap",
            "stock",
            "nasdaq",
            "sp500",
            "dow",
            "s&p",
            "treasury",
            "bond",
            "natural gas",
            "oil",
            "gold",
            "silver",
            "commodity",
        ],
        "weather": [
            "earthquake",
            "hurricane",
            "tornado",
            "weather",
            "storm",
            "flood",
            "blizzard",
            "rain",
            "snow",
            "temperature",
            "forecast",
            "climate",
            "el nino",
            "la nina",
            "typhoon",
            "cyclone",
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
            "ow2",
            "fortnite",
            "apex legends",
            "pubg",
            "call of duty",
            "cod",
            "minecraft",
            "roblox",
            "twitch",
            "steam",
            "pgl",
            "esl",
            "blizzcon",
            "worlds",
            "msi",
            "iem",
            "eleague",
            "major",
        ],
        "business": [
            "market cap",
            "ipo",
            "stock",
            "revenue",
            "profit",
            "earnings",
            "tesla",
            "apple",
            "amazon",
            "google",
            "microsoft",
            "meta",
            "tesla",
            "coinbase",
            "spacex",
            "twitter",
            "x.com",
        ],
        "entertainment": [
            "grammy",
            "oscar",
            "emmy",
            "tony",
            "movie",
            "film",
            "netflix",
            "disney",
            "hbo",
            "streaming",
            "box office",
            "album",
            "song",
            "music",
            "chart",
            "billboard",
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
            "ow2",
            "fortnite",
            "apex legends",
            "pubg",
            "call of duty",
            "cod",
            "minecraft",
            "roblox",
            "twitch",
            "steam",
            "pgl",
            "esl",
            "blizzcon",
            "worlds",
            "msi",
            "iem",
            "eleague",
            "major",
        ],
    }

    CRYPTO_SHORT_TERM_KEYWORDS = [
        "5 min",
        "15 min",
        "5m",
        "15m",
        "hourly",
        "up or down",
    ]

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

    def is_crypto_short_term(self, question: str) -> bool:
        """Check if question describes a crypto 5M/15M/hourly short-term market."""
        if not question:
            return False
        q = question.lower()
        return any(kw in q for kw in self.CRYPTO_SHORT_TERM_KEYWORDS)

    def get_category(self, question: str) -> Optional[str]:
        """Determine market category from question."""
        import re

        q = question.lower()

        # Check sports FIRST - avoid false positives from crypto
        sports_keywords = self.CATEGORY_KEYWORDS.get("sports", [])
        for kw in sports_keywords:
            # Skip certain keywords that are crypto-related
            if kw in ["magic", "jaguar"]:
                continue
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, q):
                return "sports"

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

        # Check crypto LAST - more specific
        crypto_keywords = self.CATEGORY_KEYWORDS.get("crypto", [])

        # Special handling for sports teams that share names with cryptos
        sports_team_crypto = {
            "avalanche": ["avax", "avalanche protocol"],
            "magic": ["magic coin", "magic crypto"],
            "jaguar": ["jaguar coin"],
        }

        for kw in crypto_keywords:
            # Skip single words that might be sports teams unless it's clearly crypto
            if kw in ["avalanche", "magic", "jaguar"]:
                # Check if this is the crypto version
                if kw == "avalanche" and "avax" in q.lower():
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
            m for m in markets if self.get_category(m.get("question", "")) in categories
        ]

    def check_new_markets(
        self, limit: int = 20, categories: List[str] = None
    ) -> List[Dict]:
        """Find newly created markets."""
        markets = self.api.get_active_markets(limit=limit) or []

        # Apply category filter
        if categories:
            markets = self.filter_by_category(markets, categories)

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
                    m["category"] = self.get_category(m.get("question", ""))
                    new_markets.append(m)
            except Exception:
                pass

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
            except Exception:
                pass

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

    def check_crypto_markets(
        self, limit: int = 200, markets: List[Dict] = None
    ) -> List[Dict]:
        """Get only crypto-related markets. Pass pre-fetched markets to avoid extra API call."""
        if markets is not None:
            return self.filter_by_category(markets, ["crypto"])
        m = self.api.get_active_markets(limit=limit) or []
        return self.filter_by_category(m, ["crypto"])

    def check_crypto_short_term_markets(self, limit: int = 100) -> List[Dict]:
        """Fetch crypto 5M/15M/hourly markets ordered by volume, enriched for alerts."""
        try:
            markets = self.api.get_crypto_short_term_markets(limit=limit) or []
        except Exception:
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
        if markets is not None:
            return self.filter_by_category(markets, ["sports"])
        tag_markets = []
        if hasattr(self.api, "get_sports_markets_from_events"):
            tag_markets = self.api.get_sports_markets_from_events(limit=limit) or []
        if tag_markets:
            return self.filter_by_category(tag_markets, ["sports"])
        m = self.api.get_active_markets(limit=limit) or []
        return self.filter_by_category(m, ["sports"])

    def check_politics_markets(
        self, limit: int = 400, markets: List[Dict] = None
    ) -> List[Dict]:
        """Get only politics-related markets. Pass pre-fetched markets to avoid extra API call."""
        if markets is not None:
            return self.filter_by_category(markets, ["politics"])
        m = self.api.get_active_markets(limit=limit) or []
        return self.filter_by_category(m, ["politics"])

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
            print(f"[check_crypto_moves] Error: {e}")

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
            "esports": [
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
