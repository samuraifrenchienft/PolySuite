
import unittest
import sqlite3
from datetime import datetime
from src.wallet.storage import WalletStorage
from src.wallet import Wallet

class TestWalletHistory(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.storage = WalletStorage(conn=self.conn)

    def tearDown(self):
        self.conn.close()

    def test_log_and_get_wallet_history(self):
        # Add a wallet to the database
        wallet = Wallet(
            address="test_address",
            nickname="test_wallet",
            is_smart_money=False,
            total_trades=10,
            wins=5,
            win_rate=50.0,
            trade_volume=1000
        )
        self.storage.add_wallet(wallet)

        # Log some history for the wallet
        self.storage.log_wallet_history(wallet)

        # Retrieve the history
        history = self.storage.get_wallet_history(wallet.address)

        # Assert the results
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["total_trades"], 10)
        self.assertEqual(history[0]["wins"], 5)
        self.assertAlmostEqual(history[0]["win_rate"], 50.0)
        self.assertEqual(history[0]["total_volume"], 1000)

if __name__ == '__main__':
    unittest.main()
