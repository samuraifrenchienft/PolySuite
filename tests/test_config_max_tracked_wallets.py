"""Tests for max_tracked_wallets()."""

import unittest

from src.config import DEFAULT_CONFIG, max_tracked_wallets


class TestMaxTrackedWallets(unittest.TestCase):
    def test_none_uses_default(self):
        self.assertEqual(
            max_tracked_wallets(None),
            int(DEFAULT_CONFIG.get("wallet_discovery_max_wallets", 50) or 50),
        )

    def test_dict_override(self):
        self.assertEqual(max_tracked_wallets({"wallet_discovery_max_wallets": 12}), 12)

    def test_dict_fallback_when_missing_key(self):
        self.assertEqual(
            max_tracked_wallets({}),
            int(DEFAULT_CONFIG.get("wallet_discovery_max_wallets", 100) or 100),
        )

    def test_config_like_object(self):
        class Cfg:
            def get(self, key, default=None):
                return {"wallet_discovery_max_wallets": 99}.get(key, default)

        self.assertEqual(max_tracked_wallets(Cfg()), 99)


if __name__ == "__main__":
    unittest.main()
