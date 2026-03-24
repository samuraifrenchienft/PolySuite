"""Ollama agent for natural language queries."""

import logging

try:
    import ollama

    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False
from typing import Optional, List, Dict
from src.market.api import APIClientFactory
from src.wallet.storage import WalletStorage
from src.config import Config
from src.market.bankr import BankrClient

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.2"


class Agent:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        config: Config = None,
        storage: WalletStorage = None,
        api_factory: APIClientFactory = None,
    ):
        self.model = model
        self.config = config
        self.storage = storage
        self.api_factory = api_factory
        self.bankr = (
            BankrClient(config.bankr_api_key if config else "") if config else None
        )

    def get_wallet_positions(self, address: str) -> List[Dict]:
        """Get positions for a wallet address."""
        try:
            if self.api_factory:
                pm = self.api_factory.get_polymarket_api()
                return pm.get_wallet_positions(address) or []
        except Exception:
            pass
        return []

    def get_market_info(self, condition_id: str) -> Optional[Dict]:
        """Get market info by condition ID."""
        try:
            if self.api_factory:
                pm = self.api_factory.get_polymarket_api()
                return pm.get_market(condition_id)
        except Exception:
            pass
        return None

    def chat(self, message: str) -> str:
        """Process user message and return response with real data."""
        message_lower = message.lower()

        try:
            # Bankr queries - explicit crypto/price questions
            if (
                "price" in message_lower
                or "balance" in message_lower
                or "crypto" in message_lower
                or "bankr" in message_lower
            ):
                return self._handle_bankr_query(message)
            # Polymarket/Jupiter - market questions
            elif (
                "market" in message_lower
                or "question" in message_lower
                or "event" in message_lower
            ):
                return self._handle_market_query(message)
            # Wallet/trader queries
            elif "wallet" in message_lower or "trader" in message_lower:
                return self._handle_wallet_query(message)
            elif "convergence" in message_lower or "smart money" in message_lower:
                return self._handle_convergence_query(message)
            elif "volume" in message_lower or "trending" in message_lower:
                return self._handle_volume_query(message)
            elif "jupiter" in message_lower or "solana" in message_lower:
                return self._handle_jupiter_query(message)
            elif (
                "event" in message_lower
                or "new market" in message_lower
                or "odds move" in message_lower
            ):
                return self._handle_event_query(message)
            elif "help" in message_lower:
                return self._get_help()
            else:
                return self._handle_general_query(message)
        except Exception as e:
            logger.exception("Agent error: %s", e)
            return "An error occurred. Please try again."

    def _handle_wallet_query(self, message: str) -> str:
        if not self.storage or not self.api_factory:
            return "Error: Storage or API not initialized"

        wallets = self.storage.list_wallets()
        if not wallets:
            return "No wallets tracked. Add wallets with: python main.py add <address> <nickname>"

        from src.wallet.vetting import WalletVetting

        vetter = WalletVetting(self.api_factory)
        min_bet = self.config.min_bet_size if self.config else 10.0
        results = []

        for w in wallets[:5]:
            vetting = vetter.vet_wallet(w.address, min_bet)
            if vetting:
                status = "✅" if vetting["passed"] else "❌"
                results.append(
                    f"**{w.nickname}** {status}\n"
                    f"  Win rate: {vetting['win_rate_real']:.1f}% | Trades: {vetting['total_trades']}\n"
                    f"  Avg bet: ${vetting['avg_bet_size']:.2f} | Resolved markets: {vetting['resolved_markets_traded']}\n"
                    f"  Bot score: {vetting['bot_score']}% | Unsettled losses: {vetting['unsettled_loses']}"
                )
            else:
                results.append(f"**{w.nickname}** - No trading data")

        return "### Wallet Vetting\n\n" + "\n\n".join(results)

    def _handle_market_query(self, message: str) -> str:
        if not self.api_factory:
            return "Error: API not initialized"

        api = self.api_factory.get_polymarket_api()
        markets = api.get_active_markets(limit=10)

        if not markets:
            return "No active markets found"

        results = []
        for m in markets:
            volume = m.get("volume", 0)
            results.append(
                f"**{m.get('question', 'Unknown')[:60]}**\n  Volume: ${volume:,.0f}"
            )

        return "### Active Markets\n\n" + "\n\n".join(results)

    def _handle_convergence_query(self, message: str) -> str:
        if not self.storage or not self.api_factory:
            return "Error: Storage or API not initialized"

        from src.alerts.convergence import ConvergenceDetector

        time_window = self.config.convergence_time_window_hours if self.config else 6
        max_age = self.config.convergence_max_market_age_hours if self.config else 24
        early_mins = self.config.convergence_early_entry_minutes if self.config else 10
        threshold = self.config.win_rate_threshold if self.config else 55.0

        detector = ConvergenceDetector(
            wallet_storage=self.storage,
            threshold=threshold,
            api_factory=self.api_factory,
            time_window_hours=time_window,
            max_market_age_hours=max_age,
            early_entry_minutes=early_mins,
        )

        only_early = "early" in message.lower()
        convergences = detector.find_convergences(
            min_wallets=2, only_early_entry=only_early
        )

        if not convergences:
            return "No convergences found"

        results = []
        for c in convergences[:5]:
            market = c.get("market_info") or {}
            wallets = c.get("wallets", [])
            early_tag = " [EARLY ENTRY]" if c.get("has_early_entry") else ""
            age = c.get("market_age_hours")
            age_str = f" ({age:.1f}h old)" if age else ""

            result = (
                f"**{market.get('question', 'Unknown')[:50]}**{age_str}{early_tag}\n"
            )
            result += (
                f"  {len(wallets)} traders: {', '.join(w['nickname'] for w in wallets)}"
            )

            if c.get("early_entry_wallets"):
                result += f"\n  Early entrants: {', '.join(c['early_entry_wallets'])}"

            results.append(result)

        return "### Convergences\n\n" + "\n\n".join(results)

    def _handle_volume_query(self, message: str) -> str:
        if not self.api_factory:
            return "Error: API not initialized"

        api = self.api_factory.get_polymarket_api()
        markets = api.get_active_markets(limit=20)

        if not markets:
            return "No active markets found"

        sorted_markets = sorted(markets, key=lambda m: m.get("volume", 0), reverse=True)

        results = []
        for m in sorted_markets[:10]:
            volume = m.get("volume", 0)
            results.append(f"**{m.get('question', 'Unknown')[:50]}**\n  ${volume:,.0f}")

        return "### Top Markets by Volume\n\n" + "\n\n".join(results)

    def _handle_event_query(self, message: str) -> str:
        if not self.api_factory:
            return "Error: API not initialized"

        from src.alerts.events import EventAlerter

        new_market_hours = 6
        if self.config:
            new_market_hours = getattr(self.config, "new_market_alert_hours", 6)

        alerter = EventAlerter(
            self.api_factory,
            new_market_hours=new_market_hours,
        )

        message_lower = message.lower()
        results = []

        if "new" in message_lower or "created" in message_lower:
            new_markets = alerter.check_new_markets()
            if new_markets:
                results.append("### New Markets")
                for m in new_markets[:5]:
                    hours = m.get("hours_old", 0)
                    results.append(f"- {m.get('question', '')[:50]} ({hours:.1f}h ago)")
            else:
                results.append("No new markets in the last few hours.")

        elif "volume" in message_lower or "spike" in message_lower:
            spikes = alerter.check_volume_spikes()
            if spikes:
                results.append("### Volume Spikes")
                for m in spikes[:5]:
                    results.append(
                        f"- {m.get('question', '')[:50]} ({m.get('volume_ratio', 0):.1f}x)"
                    )
            else:
                results.append("No unusual volume spikes detected.")

        elif "odds" in message_lower or "move" in message_lower:
            moves = alerter.check_odds_movements()
            if moves:
                results.append("### Odds Movements")
                for m in moves[:5]:
                    results.append(
                        f"- {m.get('question', '')[:50]} ({m.get('odds_change', 0):.0%})"
                    )
            else:
                results.append("No significant odds movements detected.")

        else:
            return alerter.get_summary()

        return (
            "\n".join(results)
            if results
            else "No events detected. Try: new markets, volume spikes, or odds movements"
        )

    def _handle_jupiter_query(self, message: str) -> str:
        if not self.api_factory:
            return "Error: API not initialized"

        jup_api = self.api_factory.get_jupiter_prediction_client()
        message_lower = message.lower()
        results = []

        if "kalshi" in message_lower:
            provider = "kalshi"
        else:
            provider = "polymarket"

        if "new" in message_lower:
            events = jup_api.get_new_events(provider=provider, limit=10)
            if events:
                results.append(f"### Jupiter New Events ({provider})")
                for e in events[:5]:
                    title = e.get("metadata", {}).get("title", "Unknown")
                    volume = e.get("volumeUsd", "$0")
                    results.append(f"- {title[:50]}\n  Volume: {volume}")
            else:
                results.append(f"No new {provider} events found.")

        elif "trending" in message_lower or "hot" in message_lower:
            events = jup_api.get_trending_events(provider=provider, limit=10)
            if events:
                results.append(f"### Jupiter Trending Events ({provider})")
                for e in events[:5]:
                    title = e.get("metadata", {}).get("title", "Unknown")
                    volume = e.get("volumeUsd", "$0")
                    results.append(f"- {title[:50]}\n  Volume: {volume}")
            else:
                results.append(f"No trending {provider} events.")

        elif "leaderboard" in message_lower or "top traders" in message_lower:
            leaders = jup_api.get_leaderboards(provider=provider, limit=10)
            if leaders:
                results.append(f"### Jupiter Top Traders ({provider})")
                for i, leader in enumerate(leaders[:5], 1):
                    pnl = leader.get("pnl", "$0")
                    volume = leader.get("volume", "$0")
                    results.append(f"{i}. PnL: {pnl} | Volume: {volume}")
            else:
                results.append("No leaderboard data.")

        else:
            events = jup_api.get_events(provider=provider, limit=10)
            if events:
                results.append(f"### Jupiter Prediction Markets ({provider})")
                for e in events[:5]:
                    title = e.get("metadata", {}).get("title", "Unknown")
                    category = e.get("category", "")
                    volume = e.get("volumeUsd", "$0")
                    results.append(f"- {title[:45]}\n  {category} | Vol: {volume}")
            else:
                results.append(f"No {provider} events found.")

        return (
            "\n\n".join(results)
            if results
            else "No data. Try: jupiter new, jupiter kalshi, jupiter trending"
        )

    def _handle_bankr_query(self, message: str) -> str:
        """Handle crypto price and balance queries via Bankr."""
        if not self.bankr or not self.bankr.is_configured():
            return "Bankr not configured. Add BANKR_API_KEY to .env"

        message_lower = message.lower()

        # Just send the whole message to Bankr - it understands natural language
        result = self._wait_for_bankr_result(message)
        if result:
            return result

        return "Could not get Bankr result. Try again."

    def _wait_for_bankr_result(self, prompt: str, timeout: int = 45) -> str:
        """Submit prompt and wait for result."""
        import time

        job_id, _ = self.bankr.send_prompt(prompt)
        if not job_id:
            return "Failed to submit Bankr query. Check API key."

        # Poll for result - Bankr takes time to process
        start = time.time()
        poll_count = 0
        while time.time() - start < timeout:
            status = self.bankr.get_job_status(job_id)
            poll_count += 1
            if status:
                if status.get("status") == "completed":
                    response = status.get("response", "")
                    if response:
                        return response
                    return "Got empty response from Bankr."
                elif status.get("status") == "failed":
                    return "Bankr query failed."
            # Wait longer between polls
            time.sleep(2)

        return f"Query timed out after {timeout}s. Try a simpler question."

    def _handle_general_query(self, message: str) -> str:
        if not self.storage or not self.api_factory:
            return "Error: Not fully initialized"

        wallets = self.storage.list_wallets()
        api = self.api_factory.get_polymarket_api()
        markets = api.get_active_markets(limit=5)

        context = f"""You are tracking {len(wallets)} wallets.
Top markets: {", ".join(m.get("question", "Unknown")[:30] for m in markets[:3])}

User asks: {message}

Provide a helpful answer about Polymarket prediction markets, smart money tracking, or the current state of tracked wallets."""

        if not OLLAMA_AVAILABLE:
            return "Ollama not installed. Run: pip install ollama"

        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": context},
                    {"role": "user", "content": message},
                ],
            )
            return response["message"]["content"]
        except Exception as e:
            logger.warning("Agent/LLM error: %s", e)
            return "AI temporarily unavailable. Try asking about: wallets, markets, convergence, volume, or whale activity"

    def _get_help(self) -> str:
        return """## Available Commands

### Wallet-Based (Follow Traders)
- **wallets** / **traders** - Your tracked wallets and vetting
- **convergence** / **smart money** - Where top traders overlap
- **early entry** - Traders who entered early on new markets

### Event-Based (Watch Markets)
- **new markets** - Recently created markets
- **volume spikes** - Unusual trading volume
- **odds movements** - Big price changes

### Jupiter (Polymarket on Solana + Kalshi)
- **jupiter** - Jupiter prediction markets
- **jupiter new** - New events on Jupiter
- **jupiter kalshi** - Kalshi markets (US regulated)
- **jupiter trending** - Hot events
- **jupiter leaderboard** - Top traders

### Bankr (Crypto Prices & More)
- **price of BTC/ETH/SOL** - Get crypto prices
- **balance** - Check wallet balance
- **polymarket markets** - Get Polymarket info
- Any crypto question!

### General
- **markets** / **questions** - Active prediction markets  
- **volume** / **trending** - Highest volume markets

Or ask anything else - I'll use the LLM with current data as context."""
