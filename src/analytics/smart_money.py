"""Smart money detection logic for PolySuite."""

from src.market.api import APIClientFactory
from src.market.leaderboard import LeaderboardImporter


class SmartMoneyDetector:
    """Detects smart money wallets based on various criteria."""

    def __init__(self, api_factory: APIClientFactory):
        """Initialize the detector."""
        self.leaderboard_importer = LeaderboardImporter(api_factory)
        self.polyscope_client = api_factory.get_polyscope_client()

    def identify_smart_money(self, min_trades=50, min_win_rate=0.65):
        """Identify smart money wallets from multiple sources."""
        smart_wallets = set()

        # 1. Get smart trader wallets from PolyScope
        polyscope_wallets = self.polyscope_client.get_smart_traders()
        for wallet in polyscope_wallets:
            smart_wallets.add(wallet["address"])

        # 2. Identify wallets with high win rates from Polymarket
        # For this, we can leverage the existing leaderboard importer to get wallet stats
        # This is a simplified example; a more robust implementation would
        # iterate through a larger set of wallets.
        top_traders = self.leaderboard_importer.fetch_leaderboard(limit=100)
        for trader in top_traders:
            stats = self.leaderboard_importer.get_wallet_stats(trader["address"])
            if (
                stats
                and stats["total_trades"] >= min_trades
                and stats["win_rate"] >= min_win_rate
            ):
                smart_wallets.add(trader["address"])

        return list(smart_wallets)
