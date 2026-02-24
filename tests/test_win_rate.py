
import unittest
from unittest.mock import MagicMock, patch
from src.wallet.calculator import WalletCalculator

class TestWinRateByCategory(unittest.TestCase):
    @patch('src.market.api.PolymarketAPI')
    def test_calculate_win_rate_by_category(self, MockAPI):
        # Mock the API and its methods
        mock_api_instance = MockAPI.return_value
        mock_api_instance.get_wallet_trades.return_value = [
            {"conditionId": "market1", "side": "BUY", "price": 0.4},
            {"conditionId": "market1", "side": "SELL", "price": 0.6},
            {"conditionId": "market2", "side": "BUY", "price": 0.7},
            {"conditionId": "market2", "side": "SELL", "price": 0.3},
        ]
        # Code deduplicates market_ids, so get_market_details is called once per market
        def market_details(market_id):
            return {"category": "Sports"} if market_id == "market1" else {"category": "Politics"}
        mock_api_instance.get_market_details.side_effect = market_details

        # Create an instance of the calculator
        mock_api_factory = MagicMock()
        mock_api_factory.get_polymarket_api.return_value = mock_api_instance
        calculator = WalletCalculator(mock_api_factory)

        # Call the method to be tested
        win_rates = calculator.calculate_win_rate_by_category("some_address")

        # Assert the results
        self.assertEqual(len(win_rates), 2)
        self.assertIn("Sports", win_rates)
        self.assertIn("Politics", win_rates)
        self.assertAlmostEqual(win_rates["Sports"]["win_rate"], 100.0)
        self.assertEqual(win_rates["Sports"]["total_trades"], 2)
        self.assertAlmostEqual(win_rates["Politics"]["win_rate"], 0.0)
        self.assertEqual(win_rates["Politics"]["total_trades"], 2)

if __name__ == '__main__':
    unittest.main()
