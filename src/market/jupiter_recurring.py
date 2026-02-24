"""Jupiter Recurring API client for DCA orders."""

import requests
from typing import Dict, List, Optional


JUPITER_RECURRING_API = "https://api.jup.ag/recurring/v1"


class JupiterRecurringAPI:
    """Client for Jupiter Recurring (DCA) API."""

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
        url = f"{JUPITER_RECURRING_API}{endpoint}"
        try:
            resp = self.session.post(url, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Error posting to {url}: {e}")
            return None

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make GET request to Jupiter API."""
        url = f"{JUPITER_RECURRING_API}{endpoint}"
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
        from_amount: str,
        to_amount: str,
        frequency: int,
        start_time: int = None,
        recurring_type: str = "time",
        slippage_bps: int = 50,
    ) -> Optional[Dict]:
        """Create a new recurring/DCA order.

        Args:
            input_mint: Token mint to sell
            output_mint: Token mint to buy
            maker: Wallet address creating the order
            from_amount: Amount per swap (in lamports)
            to_amount: Expected output amount (in lamports)
            frequency: Seconds between swaps (e.g., 86400 for daily)
            start_time: Unix timestamp to start (default now)
            recurring_type: "time" for time-based DCA
            slippage_bps: Slippage tolerance in basis points

        Returns:
            Dict with unsigned transaction
        """
        data = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "maker": maker,
            "fromAmount": from_amount,
            "toAmount": to_amount,
            "frequency": frequency,
            "recurringType": recurring_type,
            "slippageBps": slippage_bps,
        }
        if start_time:
            data["startTime"] = start_time
        return self._post("/createOrder", data)

    def execute(self, transaction: str, order: str = None) -> Optional[Dict]:
        """Execute a signed recurring order transaction.

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
        """Cancel a recurring order.

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

    def deposit_price_order(
        self, order_key: str, user_pubkey: str, amount: str
    ) -> Optional[Dict]:
        """Deposit funds into a price-based order (deprecated).

        Args:
            order_key: The order's public key
            user_pubkey: The user's wallet address
            amount: Amount to deposit

        Returns:
            Dict with deposit transaction
        """
        data = {
            "order": order_key,
            "userPubkey": user_pubkey,
            "amount": amount,
        }
        return self._post("/priceDeposit", data)

    def withdraw_price_order(
        self, order_key: str, user_pubkey: str, amount: str
    ) -> Optional[Dict]:
        """Withdraw funds from a price-based order (deprecated).

        Args:
            order_key: The order's public key
            user_pubkey: The user's wallet address
            amount: Amount to withdraw

        Returns:
            Dict with withdraw transaction
        """
        data = {
            "order": order_key,
            "userPubkey": user_pubkey,
            "amount": amount,
        }
        return self._post("/priceWithdraw", data)

    def get_orders(
        self,
        user: str,
        order_status: str = "active",
        recurring_type: str = None,
        page: int = 1,
    ) -> Optional[Dict]:
        """Get recurring orders for a wallet.

        Args:
            user: Wallet address
            order_status: "active" or "history"
            recurring_type: Optional filter by type ("time")
            page: Page number (default 1)

        Returns:
            Dict with orders list and pagination info
        """
        params = {
            "user": user,
            "orderStatus": order_status,
            "page": page,
        }
        if recurring_type:
            params["recurringType"] = recurring_type
        return self._get("/getRecurringOrders", params)

    def get_active_orders(self, user: str) -> List[Dict]:
        """Get all active recurring orders for a wallet.

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
        """Get recurring order history for a wallet.

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
