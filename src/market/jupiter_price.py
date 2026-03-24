"""Jupiter Price API v3 client for PolySuite."""

import logging
import requests
from typing import Dict, List, Optional

from src.config import Config


JUPITER_PRICE_API = "https://lite-api.jup.ag/price/v3"


class JupiterPriceAPI:
    """Client for Jupiter Price API v3."""

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

    def get_price(self, mint_addresses: List[str]) -> Optional[Dict]:
        """Get USD prices for tokens.

        Args:
            mint_addresses: List of token mint addresses (up to 50)

        Returns:
            Dict mapping mint addresses to price data
        """
        if not mint_addresses:
            return None

        ids = ",".join(mint_addresses)
        try:
            resp = self.session.get(JUPITER_PRICE_API, params={"ids": ids}, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Error fetching Jupiter price: %s", e)
            return None

    def get_single_price(self, mint_address: str) -> Optional[float]:
        """Get price for a single token.

        Args:
            mint_address: Token mint address

        Returns:
            USD price as float, or None if not available
        """
        result = self.get_price([mint_address])
        if result and mint_address in result:
            return result[mint_address].get("usdPrice")
        return None

    def get_prices_dict(self, mint_addresses: List[str]) -> Dict[str, float]:
        """Get prices as a simple dict of mint -> usd_price.

        Args:
            mint_addresses: List of token mint addresses

        Returns:
            Dict mapping mint addresses to USD prices
        """
        result = self.get_price(mint_addresses)
        if not result:
            return {}

        prices = {}
        for mint in mint_addresses:
            if mint in result:
                price = result[mint].get("usdPrice")
                if price is not None:
                    prices[mint] = price
        return prices
