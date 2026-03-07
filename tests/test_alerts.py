"""Tests for the alert system."""

import pytest
from unittest.mock import MagicMock, patch

from src.alerts.contrarian import ContrarianDetector
from src.alerts.combined import CombinedDispatcher
from src.alerts.formatter import formatter
from src.config import Config
from main import monitor


class TestContrarianAlert:
    """Test contrarian alerts."""

    def test_format_contrarian_is_actionable(self):
        """Contrarian formatter includes actionable fields."""
        mock_signal = {
            "question": "Will BTC hit $100k by EOY?",
            "vol_yes": 50000,
            "vol_no": 10000,
            "majority_side": "YES",
            "minority_side": "NO",
            "minority_price": 0.25,
            "payout": 4.0,
            "total_volume": 60000,
            "score": 12.5,
            "market_id": "0x123",
        }
        msg = formatter.format_contrarian(mock_signal)
        assert "CONTRARIAN LONG-SHOT" in msg
        assert "Crowd on YES; bet NO" in msg
        assert "[View](https://polymarket.com/market/0x123)" in msg

    @patch("main.time")
    @patch("main.CombinedDispatcher")
    @patch("main.TelegramBot")
    @patch("main.DiscordBot")
    def test_monitor_exits_cleanly_on_keyboard_interrupt(
        self, _mock_discord_bot, _mock_telegram_bot, _mock_dispatcher, mock_time
    ):
        """Monitor loop should exit without hanging when interrupted."""
        mock_config = Config("config.json")
        mock_config.config["telegram_bot_token"] = ""
        mock_config.config["discord_bot_token"] = ""

        # Trigger one loop then stop via KeyboardInterrupt in sleep.
        mock_time.time.return_value = 0
        mock_time.sleep.side_effect = KeyboardInterrupt

        storage = MagicMock()
        storage.list_wallets.return_value = []

        # Should return cleanly (KeyboardInterrupt is handled inside monitor).
        monitor(None, storage, mock_config, MagicMock())
