"""Bankr.bot integration for PolySuite - AI-powered trade execution.

Options:
1. Use default API key (BANKR_API_KEY in .env) - for personal use
2. Users connect their own Bankr account - for multi-user support
3. CLI mode - read-only operations

Note: Apply for official Polymarket API at polymarket.us/developers
      Alternative: Polymarket CLOB API at docs.polymarketexchange.com
"""

import logging
import os
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


def get_crypto_price_free(symbol: str) -> Optional[str]:
    """Get crypto price using free CoinGecko API (no key required).

    Args:
        symbol: Crypto symbol like 'bitcoin', 'ethereum', 'solana'

    Returns:
        Formatted price string or None if failed
    """
    try:
        # Map common symbols to CoinGecko IDs
        symbol_map = {
            "btc": "bitcoin",
            "eth": "ethereum",
            "sol": "solana",
            "bnb": "binancecoin",
            "xrp": "ripple",
            "ada": "cardano",
            "doge": "dogecoin",
            "dot": "polkadot",
            "matic": "matic-network",
            "link": "chainlink",
            "uni": "uniswap",
            "avax": "avalanche-2",
        }
        coin_id = symbol_map.get(symbol.lower(), symbol.lower())

        url = f"https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if coin_id in data:
                price = data[coin_id].get("usd", 0)
                change = data[coin_id].get("usd_24h_change", 0)
                return f"{coin_id.capitalize()}: ${price:,.2f} (24h: {change:+.2f}%)"
    except Exception as e:
        logger.warning("CoinGecko error: %s", type(e).__name__)
    return None


def query_openrouter(prompt: str, api_key: str = None) -> Optional[str]:
    """Query free OpenRouter AI (deepseek-r1:free model).

    Args:
        prompt: User question
        api_key: Optional OpenRouter API key for more requests

    Returns:
        AI response or None
    """
    try:
        # Use free deepseek model
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = {
            "model": "deepseek/deepseek-r1:free",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }

        resp = requests.post(url, json=data, headers=headers, timeout=30)
        if resp.status_code == 200:
            result = resp.json()
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("OpenRouter error: %s", type(e).__name__)
    return None


class BankrClient:
    """Client for Bankr.bot API for executing trades."""

    def __init__(self, api_key: str = "", user_api_key: str = ""):
        """Initialize with optional user API key.

        Args:
            api_key: Default API key from config
            user_api_key: User-provided API key (takes priority)
        """
        # User key takes priority over default
        self.api_key = user_api_key or api_key
        self.base_url = "https://api.bankr.bot"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def set_user_api_key(self, api_key: str):
        """Allow users to connect their own Bankr account."""
        self.api_key = api_key

    def send_prompt(self, prompt: str) -> tuple[Optional[str], Optional[str]]:
        """Send a natural language prompt to execute a trade.

        Returns:
            (job_id, error_msg) - job_id is None on failure; error_msg for 403/429
        """
        if not self.is_configured():
            return None, "Bankr not configured. Add BANKR_API_KEY to .env"

        try:
            resp = requests.post(
                f"{self.base_url}/agent/prompt",
                headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
                json={"prompt": prompt},
                timeout=30,
            )
            if resp.status_code in (200, 202):
                data = resp.json()
                return data.get("jobId"), None
            if resp.status_code == 401:
                try:
                    d = resp.json()
                    return None, d.get("message", "Invalid API key. Check bankr.bot/api")
                except Exception:
                    pass
                return None, "Invalid API key. Check bankr.bot/api"
            if resp.status_code == 403:
                try:
                    d = resp.json()
                    msg = d.get("message", "Access denied")
                    if "agent" in msg.lower() or "enable" in msg.lower():
                        return None, "❌ Agent API not enabled. Enable at bankr.bot/api"
                except Exception:
                    pass
                return None, "❌ Bankr access denied (403). Enable Agent API at bankr.bot/api"
            if resp.status_code == 429:
                try:
                    d = resp.json()
                    msg = d.get("message", "Rate limit exceeded")
                    return None, f"❌ {msg}"
                except Exception:
                    pass
                return None, "❌ Daily limit exceeded (100 msg/day free). Upgrade at bankr.bot"
            return None, "Bankr error"
        except Exception as e:
            logger.warning("[Bankr] Error: %s", type(e).__name__)
            return None, "Request failed"
        return None, "Failed to submit"

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Check the status of a job."""
        if not self.is_configured():
            return None

        try:
            resp = requests.get(
                f"{self.base_url}/agent/job/{job_id}",
                headers={"X-API-Key": self.api_key},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Handle both 'result' and 'response' fields
                if data.get("status") == "completed":
                    data["result"] = data.get("response", "") or data.get("result", "")
                return data
        except Exception as e:
            print(f"[Bankr] Error: {e}")
        return None

    def execute_polymarket_bet(
        self, amount: float, outcome: str, market_id: str
    ) -> Optional[str]:
        """Execute a Polymarket bet via Bankr.

        Args:
            amount: Amount in USD
            outcome: "yes" or "no"
            market_id: Polymarket market ID
        """
        prompt = f"bet ${amount} on {outcome} for market {market_id} on Polymarket"
        job_id, _ = self.send_prompt(prompt)
        return job_id

    def check_balance(self, chain: str = "base") -> Optional[str]:
        """Check wallet balance on a chain."""
        job_id, _ = self.send_prompt(f"what is my balance on {chain}?")
        return job_id

    def get_eth_price(self) -> Optional[str]:
        """Get current ETH price."""
        job_id, _ = self.send_prompt("what is the price of ETH?")
        return job_id

    def deploy_token(
        self,
        token_name: str,
        token_symbol: str = None,
        description: str = None,
        fee_recipient: str = None,
        simulate_only: bool = False,
    ) -> Optional[Dict]:
        """Deploy a token via Bankr API.

        Args:
            token_name: Name of the token (required)
            token_symbol: Symbol/ticker (optional, auto-generated)
            description: Token description (optional)
            fee_recipient: Wallet address to receive fees (optional)
            simulate_only: Just simulate without deploying

        Returns:
            Dict with tokenAddress, poolId, txHash, etc.
        """
        if not self.is_configured():
            return None

        try:
            data = {"tokenName": token_name, "simulateOnly": simulate_only}

            if token_symbol:
                data["tokenSymbol"] = token_symbol
            if description:
                data["description"] = description
            if fee_recipient:
                data["feeRecipient"] = {"type": "wallet", "value": fee_recipient}

            resp = requests.post(
                f"{self.base_url}/token-launches/deploy",
                headers={"Content-Type": "application/json", "X-API-Key": self.api_key},
                json=data,
                timeout=60,
            )

            if resp.status_code in (200, 201):
                return resp.json()
            else:
                logger.warning("[Bankr] Deploy error: %s", resp.status_code)
                return {"error": "Deploy failed", "status": resp.status_code}

        except Exception as e:
            logger.warning("[Bankr] Deploy exception: %s", type(e).__name__)
            return None

    def read_only_query(self, query: str) -> Optional[str]:
        """Read-only query (for CLI mode).

        These queries don't execute trades, just get info:
        - "what is the price of BTC?"
        - "show my balances"
        - "what markets are trending?"
        """
        read_only_prefixes = [
            "what is",
            "show",
            "list",
            "get",
            "display",
            "check",
            "find",
            "search",
            "lookup",
        ]

        # Only allow read-only prompts
        query_lower = query.lower().strip()
        is_read_only = any(
            query_lower.startswith(prefix) for prefix in read_only_prefixes
        )

        # Block trade keywords
        blocked = ["buy", "sell", "swap", "trade", "bet", "purchase", "order"]
        if any(word in query_lower for word in blocked):
            if not is_read_only:
                print("[Bankr] Read-only mode: blocking trade command")
                return None

        job_id, _ = self.send_prompt(query)
        return job_id


class BankrCLI:
    """Bankr CLI wrapper for read-only operations."""

    def __init__(self, api_key: str = ""):
        self.client = BankrClient(api_key)

    def is_configured(self) -> bool:
        return self.client.is_configured()

    def query(self, question: str) -> Optional[str]:
        """Ask a read-only question."""
        return self.client.read_only_query(question)

    def get_prices(self, tokens: List[str] = None) -> Dict[str, str]:
        """Get prices for common tokens."""
        if tokens is None:
            tokens = ["BTC", "ETH", "SOL", "BNKR"]

        prices = {}
        for token in tokens:
            result = self.query(f"what is the price of {token}?")
            if result:
                prices[token] = result
        return prices

    def get_balances(self) -> Optional[str]:
        """Get all balances."""
        return self.query("show my balances")

    def get_trending_markets(self) -> Optional[str]:
        """Get trending Polymarket markets."""
        return self.query("what are the trending Polymarket markets?")

    def deploy_token(
        self,
        token_name: str,
        token_symbol: str = None,
        description: str = None,
        fee_recipient: str = None,
        simulate_only: bool = False,
    ) -> Optional[Dict]:
        """Deploy a token via Bankr API.

        Args:
            token_name: Name of the token (required)
            token_symbol: Symbol/ticker (optional, auto-generated)
            description: Token description (optional)
            fee_recipient: Wallet address to receive fees (optional)
            simulate_only: Just simulate without deploying

        Returns:
            Dict with tokenAddress, poolId, txHash, etc.
        """
        if not self.is_configured():
            return None

        try:
            data = {"tokenName": token_name, "simulateOnly": simulate_only}

            if token_symbol:
                data["tokenSymbol"] = token_symbol
            if description:
                data["description"] = description
            if fee_recipient:
                data["feeRecipient"] = {"type": "wallet", "value": fee_recipient}

            resp = requests.post(
                f"{self.client.base_url}/token-launches/deploy",
                headers={"Content-Type": "application/json", "X-API-Key": self.client.api_key},
                json=data,
                timeout=60,
            )

            if resp.status_code in (200, 201):
                return resp.json()
            else:
                logger.warning("[Bankr] Deploy error: %s", resp.status_code)
                return {"error": "Deploy failed", "status": resp.status_code}

        except Exception as e:
            logger.warning("[Bankr] Deploy exception: %s", type(e).__name__)
            return None
