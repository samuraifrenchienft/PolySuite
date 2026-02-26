"""Tests for dashboard auth and initData validation."""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestValidateTelegramInitData(unittest.TestCase):
    """Test _validate_telegram_init_data from dashboard app."""

    def test_empty_init_data_returns_false(self):
        from src.dashboard.app import _validate_telegram_init_data

        self.assertFalse(_validate_telegram_init_data("", "bot_token"))
        self.assertFalse(_validate_telegram_init_data(None, "bot_token"))

    def test_empty_bot_token_returns_false(self):
        from src.dashboard.app import _validate_telegram_init_data

        self.assertFalse(_validate_telegram_init_data("query_id=AA&auth_date=123", ""))

    def test_missing_hash_returns_false(self):
        from src.dashboard.app import _validate_telegram_init_data

        # initData without hash is invalid
        invalid = "query_id=AA&auth_date=123"
        self.assertFalse(_validate_telegram_init_data(invalid, "fake_bot_token"))

    def test_invalid_hash_returns_false(self):
        from src.dashboard.app import _validate_telegram_init_data

        # initData with wrong hash
        invalid = "query_id=AA&auth_date=9999999999&hash=wrong"
        self.assertFalse(_validate_telegram_init_data(invalid, "fake_bot_token"))


class TestDashboardAuth(unittest.TestCase):
    """Test dashboard auth when DASHBOARD_API_KEY is set."""

    @patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key-123", "DASHBOARD_REQUIRE_AUTH": "1"})
    def test_requires_api_key_when_configured(self):
        from flask_socketio import SocketIO
        from src.dashboard.app import Dashboard
        from src.wallet.storage import WalletStorage

        storage = WalletStorage()
        socketio = SocketIO()
        dash = Dashboard(storage, socketio)

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
