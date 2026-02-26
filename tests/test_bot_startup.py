"""Tests for bot startup with empty/whitespace token validation."""

import unittest
from unittest.mock import MagicMock, patch


class TestBotStartupTokenValidation(unittest.TestCase):
    """Verify bots do not start when token is empty or whitespace."""

    @patch("main.TelegramBot")
    def test_handle_bot_command_empty_token_does_not_start_bot(self, mock_telegram_bot):
        from main import handle_bot_command

        args = MagicMock()
        storage = MagicMock()
        config = MagicMock()
        config.telegram_bot_token = ""
        api_factory = MagicMock()

        handle_bot_command(args, storage, config, api_factory)

        mock_telegram_bot.assert_not_called()

    @patch("main.TelegramBot")
    def test_handle_bot_command_whitespace_token_does_not_start_bot(self, mock_telegram_bot):
        from main import handle_bot_command

        args = MagicMock()
        storage = MagicMock()
        config = MagicMock()
        config.telegram_bot_token = "   "
        api_factory = MagicMock()

        handle_bot_command(args, storage, config, api_factory)

        mock_telegram_bot.assert_not_called()

    @patch("main.DiscordBot")
    def test_handle_discord_command_empty_token_does_not_start_bot(self, mock_discord_bot):
        from main import handle_discord_command

        args = MagicMock()
        storage = MagicMock()
        config = MagicMock()
        config.discord_bot_token = ""
        api_factory = MagicMock()

        handle_discord_command(args, storage, config, api_factory)

        mock_discord_bot.assert_not_called()

    @patch("main.DiscordBot")
    def test_handle_discord_command_whitespace_token_does_not_start_bot(self, mock_discord_bot):
        from main import handle_discord_command

        args = MagicMock()
        storage = MagicMock()
        config = MagicMock()
        config.discord_bot_token = "   \t  "
        api_factory = MagicMock()

        handle_discord_command(args, storage, config, api_factory)

        mock_discord_bot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
