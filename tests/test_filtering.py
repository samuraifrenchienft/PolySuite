
import unittest
from unittest.mock import MagicMock, patch
from argparse import Namespace

from src.wallet import Wallet
from main import list_wallets

class TestFiltering(unittest.TestCase):

    def setUp(self):
        self.mock_storage = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.win_rate_threshold = 55.0
        self.mock_api_factory = MagicMock()

        self.wallets = [
            Wallet(address='0x1', nickname='wallet1', total_trades=10, trade_volume=1000, wins=5, win_rate=50.0, is_smart_money=False),
            Wallet(address='0x2', nickname='wallet2', total_trades=20, trade_volume=2000, wins=10, win_rate=50.0, is_smart_money=False),
            Wallet(address='0x3', nickname='wallet3', total_trades=30, trade_volume=3000, wins=15, win_rate=50.0, is_smart_money=False),
        ]

        self.args = Namespace(min_trades=None, min_volume=None, min_recent_trades=None, by_category=False, recent_days=7)

    @patch('builtins.print')
    def test_list_wallets_no_filters(self, mock_print):
        self.mock_storage.list_wallets.return_value = self.wallets
        
        list_wallets(self.args, self.mock_storage, self.mock_config, self.mock_api_factory)
        
        self.assertEqual(mock_print.call_count, 4)

    @patch('builtins.print')
    def test_list_wallets_min_trades_filter(self, mock_print):
        self.args.min_trades = 15
        self.mock_storage.list_wallets.return_value = self.wallets[1:]

        list_wallets(self.args, self.mock_storage, self.mock_config, self.mock_api_factory)

        self.assertEqual(mock_print.call_count, 3)

    @patch('builtins.print')
    def test_list_wallets_min_volume_filter(self, mock_print):
        self.args.min_volume = 2500
        self.mock_storage.list_wallets.return_value = self.wallets[2:]

        list_wallets(self.args, self.mock_storage, self.mock_config, self.mock_api_factory)

        self.assertEqual(mock_print.call_count, 2)

    @patch('main.WalletCalculator')
    @patch('builtins.print')
    def test_list_wallets_recent_trades_filter(self, mock_print, mock_wallet_calculator):
        self.args.min_recent_trades = 5
        self.mock_storage.list_wallets.return_value = self.wallets
        
        mock_calculator_instance = mock_wallet_calculator.return_value
        mock_calculator_instance.count_recent_trades.side_effect = [2, 6, 8] # wallet1, wallet2, wallet3

        list_wallets(self.args, self.mock_storage, self.mock_config, self.mock_api_factory)

        self.assertEqual(mock_print.call_count, 3)

if __name__ == '__main__':
    unittest.main()
