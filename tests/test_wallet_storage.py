"""Comprehensive unit tests for WalletStorage."""

import os
import tempfile
import unittest
from pathlib import Path

from src.wallet import Wallet
from src.wallet.storage import WalletStorage


class TestWalletStorage(unittest.TestCase):
    """Test WalletStorage CRUD and core operations."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_wallet(self):
        storage = WalletStorage(db_path=self.db_path)
        w = Wallet(address="0x1234567890123456789012345678901234567890", nickname="Test1")
        self.assertTrue(storage.add_wallet(w))
        self.assertFalse(storage.add_wallet(w))  # duplicate

    def test_get_wallet(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
        w = Wallet(address=addr, nickname="Test2")
        storage.add_wallet(w)
        got = storage.get_wallet(addr)
        self.assertIsNotNone(got)
        self.assertEqual(got.address.lower(), addr.lower())
        self.assertEqual(got.nickname, "Test2")
        self.assertIsNone(storage.get_wallet("0x0000000000000000000000000000000000000000"))

    def test_remove_wallet(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0x1111111111111111111111111111111111111111"
        storage.add_wallet(Wallet(address=addr, nickname="R"))
        self.assertTrue(storage.remove_wallet(addr))
        self.assertIsNone(storage.get_wallet(addr))
        self.assertFalse(storage.remove_wallet(addr))

    def test_list_wallets(self):
        storage = WalletStorage(db_path=self.db_path)
        for i in range(3):
            addr = f"0x{i:040x}"
            storage.add_wallet(Wallet(address=addr, nickname=f"W{i}"))
        all_w = storage.list_wallets()
        self.assertEqual(len(all_w), 3)

    def test_list_wallets_min_trades(self):
        storage = WalletStorage(db_path=self.db_path)
        w1 = Wallet(address="0x" + "1" * 40, nickname="A", total_trades=5)
        w2 = Wallet(address="0x" + "2" * 40, nickname="B", total_trades=15)
        storage.add_wallet(w1)
        storage.add_wallet(w2)
        storage.update_wallet(w1)
        storage.update_wallet(w2)
        filtered = storage.list_wallets(min_trades=10)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].total_trades, 15)

    def test_update_wallet(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0x" + "3" * 40
        w = Wallet(address=addr, nickname="U", total_trades=0, win_rate=0)
        storage.add_wallet(w)
        w.total_trades = 50
        w.wins = 30
        w.win_rate = 60.0
        self.assertTrue(storage.update_wallet(w))
        got = storage.get_wallet(addr)
        self.assertEqual(got.total_trades, 50)
        self.assertEqual(got.win_rate, 60.0)

    def test_update_wallet_stats(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0x" + "4" * 40
        storage.add_wallet(Wallet(address=addr, nickname="S"))
        self.assertTrue(storage.update_wallet_stats(addr, 20, 12, 5000))
        got = storage.get_wallet(addr)
        self.assertEqual(got.total_trades, 20)
        self.assertEqual(got.wins, 12)
        self.assertEqual(got.win_rate, 60.0)

    def test_get_high_performers(self):
        storage = WalletStorage(db_path=self.db_path)
        for i, (tr, wr) in enumerate([(10, 55), (10, 70), (5, 80)]):
            addr = f"0x{i:040x}"
            w = Wallet(address=addr, nickname=f"H{i}", total_trades=tr, wins=int(tr * wr / 100), win_rate=wr)
            storage.add_wallet(w)
            storage.update_wallet(w)
        hp = storage.get_high_performers(threshold=55)
        self.assertGreaterEqual(len(hp), 2)

    def test_change_tier(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0x" + "5" * 40
        storage.add_wallet(Wallet(address=addr, nickname="T"))
        self.assertTrue(storage.change_tier(addr, "vetted", "Manual test"))
        got = storage.get_wallet(addr)
        self.assertEqual(got.tier, "vetted")

    def test_get_wallets_by_tier(self):
        storage = WalletStorage(db_path=self.db_path)
        for i in range(4):
            addr = f"0x{i:040x}"
            w = Wallet(address=addr, nickname=f"T{i}", tier="vetted" if i < 2 else "watch")
            storage.add_wallet(w)
            storage.update_wallet(w)
        vetted = storage.get_wallets_by_tier("vetted")
        self.assertEqual(len(vetted), 2)

    def test_get_wallet_history(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0x" + "6" * 40
        w = Wallet(address=addr, nickname="Hist", total_trades=10, wins=6, win_rate=60)
        storage.add_wallet(w)
        storage.log_wallet_history(w)
        hist = storage.get_wallet_history(addr)
        self.assertGreaterEqual(len(hist), 1)

    def test_get_all_wallets_with_scores(self):
        storage = WalletStorage(db_path=self.db_path)
        addr = "0x" + "7" * 40
        storage.add_wallet(Wallet(address=addr, nickname="Sc", total_score=75))
        storage.update_wallet(Wallet(address=addr, nickname="Sc", total_score=75))
        all_w = storage.get_all_wallets_with_scores()
        self.assertGreaterEqual(len(all_w), 1)

    def test_get_db_size(self):
        storage = WalletStorage(db_path=self.db_path)
        storage.add_wallet(Wallet(address="0x" + "8" * 40, nickname="Sz"))
        size = storage.get_db_size()
        self.assertGreater(size, 0)
