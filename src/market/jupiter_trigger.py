"""Jupiter Trigger API client for limit orders."""

import requests
from typing import Dict, List, Optional


JUPITER_TRIGGER_API = "https://api.jup.ag/trigger/v1"


class JupiterTriggerAPI:
    """Client for Jupiter Trigger (Limit Order) API."""

    def __init__(self, api_key: str = None):
        """Initialize API client."""
        self.session = requests.Session()
        self.api_key = api_key
        if api_key:
            self.session.headers["x-api-key"] = api_key
        self.session.headers["Content-Type"] = "application/json"

    def close(self):
        """Close the session."""
        self.session.close()

    def _post(self, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Make POST request to Jupiter API."""
        url = f"{JUPITER_TRIGGER_API}{endpoint}"
        try:
            resp = self.session.post(url, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Error posting to {url}: {e}")
            return None

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make GET request to Jupiter API."""
        url = f"{JUPITER_TRIGGER_API}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def create_order(
        self,
        input_mint: str,
        output_mint: str,
        maker: str,
        making_amount: str,
        taking_amount: str,
        mode: str = "Ultra",
    ) -> Optional[Dict]:
        """Create a new trigger/limit order.

        Args:
            input_mint: Token mint to sell
            output_mint: Token mint to buy
            maker: Wallet address creating the order
            making_amount: Amount of input token to sell (in lamports/smallest unit)
            taking_amount: Amount of output token wanted
            mode: "Ultra" or "Exact" (Ultra adds slippage protection)

        Returns:
            Dict with unsigned transaction
        """
        data = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "maker": maker,
            "makingAmount": making_amount,
            "takingAmount": taking_amount,
            "mode": mode,
        }
        return self._post("/createOrder", data)

    def execute(self, transaction: str, order: str = None) -> Optional[Dict]:
        """Execute a signed transaction.

        Args:
            transaction: Base64-encoded signed transaction
            order: Optional order identifier

        Returns:
            Dict with execution status
        """
        data = {"transaction": transaction}
        if order:
            data["order"] = order
        return self._post("/execute", data)

    def cancel_order(self, order_key: str, user_pubkey: str) -> Optional[Dict]:
        """Cancel a trigger order.

        Args:
            order_key: The order's public key
            user_pubkey: The user's wallet address

        Returns:
            Dict with unsigned cancel transaction
        """
        data = {
            "order": order_key,
            "userPubkey": user_pubkey,
        }
        return self._post("/cancelOrder", data)

    def cancel_orders(self, order_keys: List[str], user_pubkey: str) -> Optional[Dict]:
        """Cancel multiple trigger orders.

        Args:
            order_keys: List of order public keys
            user_pubkey: The user's wallet address

        Returns:
            Dict with unsigned cancel transactions
        """
        data = {
            "orders": order_keys,
            "userPubkey": user_pubkey,
        }
        return self._post("/cancelOrders", data)

    def get_orders(
        self,
        user: str,
        order_status: str = "active",
        input_mint: str = None,
        output_mint: str = None,
        page: int = 1,
    ) -> Optional[Dict]:
        """Get trigger orders for a wallet.

        Args:
            user: Wallet address
            order_status: "active" or "history"
            input_mint: Optional filter by input token
            output_mint: Optional filter by output token
            page: Page number (default 1)

        Returns:
            Dict with orders list and pagination info
        """
        params = {
            "user": user,
            "orderStatus": order_status,
            "page": page,
        }
        if input_mint:
            params["inputMint"] = input_mint
        if output_mint:
            params["outputMint"] = output_mint
        return self._get("/getTriggerOrders", params)

    def get_active_orders(self, user: str) -> List[Dict]:
        """Get all active trigger orders for a wallet.

        Args:
            user: Wallet address

        Returns:
            List of active orders
        """
        result = self.get_orders(user, "active")
        if result and "orders" in result:
            return result["orders"]
        return []

    def get_order_history(self, user: str, page: int = 1) -> List[Dict]:
        """Get order history for a wallet.

        Args:
            user: Wallet address
            page: Page number

        Returns:
            List of historical orders
        """
        result = self.get_orders(user, "history", page=page)
        if result and "orders" in result:
            return result["orders"]
        return []
