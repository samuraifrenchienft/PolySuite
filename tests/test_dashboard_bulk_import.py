"""Tests for dashboard bulk import and wallet persistence."""

import os
import tempfile
import unittest
from pathlib import Path

from src.wallet import Wallet
from src.wallet.storage import WalletStorage
from src.dashboard.app import Dashboard


class TestDashboardBulkImport(unittest.TestCase):
    """Test bulk import saves wallets to database."""

    def setUp(self):
        """Use temp DB for each test."""
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up temp dir."""
        import shutil
        if os.path.exists(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bulk_import_saves_to_database(self):
        """Bulk import should persist wallets to storage."""
        storage = WalletStorage(db_path=self.db_path)
        dash = Dashboard(storage)

        valid_addr = "0x1234567890123456789012345678901234567890"
        wallets_text = f"{valid_addr}\n0xabcdefabcdefabcdefabcdefabcdefabcdefabcd,Nick2"

        with dash.app.test_client() as client:
            resp = client.post(
                "/api/wallets/bulk-import",
                json={"wallets": wallets_text, "auto_vet": False},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(data.get("imported_count", 0), 1)

        # Verify wallets appear in database
        listed = storage.list_wallets()
        addresses = [w.address.lower() for w in listed]
        self.assertIn(valid_addr.lower(), addresses)
        self.assertIn("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd", addresses)

    def test_bulk_import_creates_wallet_object(self):
        """Bulk import should use Wallet object for add_wallet."""
        storage = WalletStorage(db_path=self.db_path)
        dash = Dashboard(storage)

        addr = "0x1111111111111111111111111111111111111111"
        with dash.app.test_client() as client:
            resp = client.post(
                "/api/wallets/bulk-import",
                json={"wallets": addr},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        wallet = storage.get_wallet(addr)
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.address.lower(), addr.lower())
        self.assertIsInstance(wallet, Wallet)
