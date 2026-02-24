"""Client for interacting with the Jupiter API."""

import requests
from src.config import Config


JUPITER_API_URL = "https://api.jup.ag"


class JupiterClient:
    """A client for the Jupiter API."""

    def __init__(self):
        """Initialize the client."""
        self.config = Config()
        self.api_url = JUPITER_API_URL
        self.headers = {
            "Content-Type": "application/json",
        }
        # Use x-api-key header for authentication
        if self.config.jupiter_id:
            self.headers["x-api-key"] = self.config.jupiter_id

    def get_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ):
        """Get a quote for a swap."""
        try:
            response = requests.get(
                f"{self.api_url}/swap/v1/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount,
                    "slippageBps": slippage_bps,
                },
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()  # Raise an exception for bad status codes
            try:
                return response.json()
            except requests.exceptions.JSONDecodeError as e:
                print(f"Error decoding JSON from Jupiter quote API: {e}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error getting quote from Jupiter API: {e}")
            return None

    def get_swap_instructions(self, quote_response: dict, user_public_key: str):
        """Get swap instructions."""
        try:
            response = requests.post(
                f"{self.api_url}/swap",
                json={
                    "quoteResponse": quote_response,
                    "userPublicKey": user_public_key,
                    "wrapAndUnwrapSol": True,
                },
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()
            try:
                return response.json()
            except requests.exceptions.JSONDecodeError as e:
                print(f"Error decoding JSON from Jupiter swap API: {e}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error getting swap instructions from Jupiter API: {e}")
            return None
