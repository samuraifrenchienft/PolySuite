"""Tests for dashboard auth and initData validation."""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestDashboardAuth(unittest.TestCase):
    """Test dashboard auth when DASHBOARD_API_KEY is set."""

    @patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key-123", "DASHBOARD_REQUIRE_AUTH": "1"})
    def test_requires_api_key_when_configured(self):
        from src.dashboard.app import Dashboard
        from src.wallet.storage import WalletStorage

        storage = WalletStorage()
        dash = Dashboard(storage)

        with dash.app.test_client() as client:
            # Without API key - should get 401
            resp = client.get("/")
            self.assertEqual(resp.status_code, 401)

            # With correct API key
            resp = client.get("/", headers={"X-API-Key": "test-key-123"})
            self.assertEqual(resp.status_code, 200)

            # With wrong API key
            resp = client.get("/", headers={"X-API-Key": "wrong-key"})
            self.assertEqual(resp.status_code, 401)
