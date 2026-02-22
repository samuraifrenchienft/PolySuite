"""Wallet-to-market mapping for PolySuite."""

from typing import List, Dict, Set, Optional
from src.market.api import get_api
from src.market.storage import MarketStorage


class WalletMarketMapper:
    """Maps wallets to their market positions."""

    def __init__(self, api=None, storage: MarketStorage = None):
        """Initialize mapper."""
        self.api = api or get_api()
        self.storage = storage or MarketStorage()

    def sync_wallet_positions(self, wallet_address: str) -> List[Dict]:
        """Sync wallet positions from API and store in DB.

        Args:
            wallet_address: The wallet to sync

        Returns:
            List of positions
        """
        try:
            positions = (
                self.api.get_wallet_positions(wallet_address) if self.api else []
            )
        except Exception:
            positions = []

        for pos in positions:
            market_id = pos.get("conditionId") or pos.get("market")
            if market_id:
                # Save market info
                market = self.api.get_market(market_id)
                if market:
                    self.storage.save_market(market)

                # Save wallet-market relationship
                self.storage.save_wallet_market(wallet_address, market_id, pos)

        return positions

    def get_wallet_markets(self, wallet_address: str) -> List[Dict]:
        """Get all markets a wallet has traded in.

        Args:
            wallet_address: The wallet address

        Returns:
            List of market info dicts
        """
        return self.storage.get_markets_for_wallet(wallet_address)

    def get_market_wallets(self, market_id: str) -> List[str]:
        """Get all wallets that traded in a market.

        Args:
            market_id: The market ID

        Returns:
            List of wallet addresses
        """
        return self.storage.get_wallets_in_market(market_id)

    def find_convergences(
        self, wallet_addresses: List[str], min_wallets: int = 2
    ) -> List[Dict]:
        """Find markets where multiple tracked wallets are active.

        Args:
            wallet_addresses: List of wallet addresses to check
            min_wallets: Minimum number of wallets in same market

        Returns:
            List of convergence dicts with market and wallets
        """
        # Build market -> wallets mapping
        market_wallets: Dict[str, Set[str]] = {}

        for wallet in wallet_addresses:
            markets = self.get_wallet_markets(wallet)
            for market in markets:
                market_id = market.get("market_id")
                if market_id:
                    if market_id not in market_wallets:
                        market_wallets[market_id] = set()
                    market_wallets[market_id].add(wallet)

        # Find convergences
        convergences = []
        for market_id, wallets in market_wallets.items():
            if len(wallets) >= min_wallets:
                market = self.storage.get_market(market_id)
                convergences.append(
                    {
                        "market_id": market_id,
                        "market": market,
                        "wallets": list(wallets),
                        "count": len(wallets),
                    }
                )

        return convergences

    def get_wallet_with_positions(self, wallet_address: str) -> List[Dict]:
        """Get wallet with full position details.

        Args:
            wallet_address: The wallet address

        Returns:
            List of positions with market details
        """
        try:
            positions = (
                self.api.get_wallet_positions(wallet_address) if self.api else []
            )
        except Exception:
            positions = []
        result = []

        for pos in positions:
            market_id = pos.get("conditionId") or pos.get("market")
            if market_id:
                market = self.api.get_market(market_id)
                result.append({"position": pos, "market": market})

        return result
