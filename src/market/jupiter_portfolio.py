"""Jupiter Portfolio API client for PolySuite."""

import logging
import requests
from typing import Dict, List, Optional

from src.config import Config

logger = logging.getLogger(__name__)

JUPITER_ULTRA_API = "https://api.jup.ag/ultra/v1"


class JupiterPortfolioAPI:
    """Client for Jupiter Portfolio/Holdings API."""

    def __init__(self, api_key: str = None):
        """Initialize API client."""
        self.session = requests.Session()
        config = Config()
        self.api_key = api_key or config.jupiter_id
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key

    def close(self):
        """Close the session."""
        self.session.close()

    def get_holdings(self, address: str) -> Optional[Dict]:
        """Get all token holdings for a wallet.

        Args:
            address: Solana wallet address

        Returns:
            Dict with 'sol' balance and 'tokens' list
        """
        try:
            resp = self.session.get(
                f"{JUPITER_ULTRA_API}/holdings/{address}", timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Error fetching Jupiter holdings: %s", e)
            return None

    def get_native_sol(self, address: str) -> Optional[float]:
        """Get native SOL balance for a wallet.

        Args:
            address: Solana wallet address

        Returns:
            SOL balance as float, or None if error
        """
        try:
            resp = self.session.get(
                f"{JUPITER_ULTRA_API}/holdings/{address}/native", timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("lamports", 0)) / 1e9
        except Exception as e:
            logger.warning("Error fetching native SOL: %s", e)
            return None

    def get_token_list(self, address: str) -> List[Dict]:
        """Get list of tokens in a wallet with their amounts.

        Args:
            address: Solana wallet address

        Returns:
            List of token holdings
        """
        holdings = self.get_holdings(address)
        if holdings:
            return holdings.get("tokens", [])
        return []

    def get_portfolio_summary(self, address: str) -> Dict:
        """Get a summary of the portfolio.

        Args:
            address: Solana wallet address

        Returns:
            Dict with total tokens, SOL balance, and token list
        """
        holdings = self.get_holdings(address)
        if not holdings:
            return {"sol": 0, "tokens": [], "count": 0}

        tokens = holdings.get("tokens", [])
        return {
            "sol": float(holdings.get("sol", 0)),
            "tokens": tokens,
            "count": len(tokens),
        }
