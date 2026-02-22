"""Configuration for PolySuite."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any


from dotenv import load_dotenv


DEFAULT_CONFIG = {
    "win_rate_threshold": 55.0,
    "min_trades_for_high_performer": 10,
    "polling_interval": 60,
    "alert_cooldown": 300,
    "tracked_wallets": [],
    "tracked_categories": [],
    "trade_volume_threshold": 1000,
    "position_size_threshold": 1000,
    "leaderboard_import_interval": 3600,  # 1 hour
}

# Shared Bankr client instance
_bankr_client = None


def get_bankr_client(api_key: str = None) -> "BankrClient":
    """Get or create shared Bankr client."""
    global _bankr_client
    if _bankr_client is None and api_key:
        from src.market.bankr import BankrClient

        _bankr_client = BankrClient(api_key)
    return _bankr_client


# Secrets that will be loaded from .env
SECRET_KEYS = [
    "discord_bot_token",
    "discord_webhook_url",
    "discord_application_id",
    "telegram_bot_token",
    "telegram_chat_id",
    "polymarket_api_key",
    "polymarket_api_secret",
    "polymarket_api_passphrase",
    "domeapi_key",
    "prediedge_api_key",
    "jupiter_api_key",
    "jupiter_id",
    "bankr_api_key",
    "hashdive_api_key",
]

# Backup config defaults
DEFAULT_BACKUP_INTERVAL_HOURS = 6
DEFAULT_BACKUP_KEEP_DAYS = 7


class Config:
    """Configuration manager for PolySuite."""

    def __init__(self, config_path: str = "config.json"):
        """Initialize config from file or defaults."""
        self.config_path = config_path
        self.config = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load config from multiple sources with precedence.

        Precedence:
        1. Environment variables (for secrets)
        2. config.json file (for non-secrets)
        3. Default config
        """
        load_dotenv()

        # Start with default config
        config = DEFAULT_CONFIG.copy()

        # Load from config.json for non-secret values
        if Path(self.config_path).exists():
            try:
                with open(self.config_path, "r") as f:
                    loaded_from_file = json.load(f)
                    config.update(loaded_from_file)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error loading config file: {e}")
                print("Using default configuration for non-secrets.")

        # Load secrets from environment variables, overriding any other values
        for key in SECRET_KEYS:
            env_value = os.getenv(key.upper())
            if env_value:
                config[key] = env_value

        return config

    def save(self) -> None:
        """Save config to file."""
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set config value."""
        self.config[key] = value

    @property
    def win_rate_threshold(self) -> float:
        return self.config.get("win_rate_threshold", 55.0)

    @property
    def discord_bot_token(self) -> str:
        return self.config.get("discord_bot_token", "")

    @property
    def discord_application_id(self) -> str:
        return self.config.get("discord_application_id", "")

    @property
    def discord_webhook_url(self) -> str:
        return self.config.get("discord_webhook_url", "")

    @property
    def polling_interval(self) -> int:
        return self.config.get("polling_interval", 60)

    @property
    def alert_cooldown(self) -> int:
        return self.config.get("alert_cooldown", 300)

    @property
    def alert_cooldown_convergence(self) -> int:
        return self.config.get("alert_cooldown_convergence", 1800)

    @property
    def alert_cooldown_arb(self) -> int:
        return self.config.get("alert_cooldown_arb", 900)

    @property
    def alert_cooldown_new_market(self) -> int:
        return self.config.get("alert_cooldown_new_market", 3600)

    @property
    def alert_cooldown_volume_spike(self) -> int:
        return self.config.get("alert_cooldown_volume_spike", 1800)

    @property
    def alert_cooldown_odds_move(self) -> int:
        return self.config.get("alert_cooldown_odds_move", 900)

    @property
    def expiring_soon_hours(self) -> int:
        return self.config.get("expiring_soon_hours", 2)

    @property
    def crypto_15m_move_threshold(self) -> float:
        return self.config.get("crypto_15m_move_threshold", 0.03)

    @property
    def crypto_5m_move_threshold(self) -> float:
        return self.config.get("crypto_5m_move_threshold", 0.015)

    @property
    def tracked_crypto(self) -> list:
        return self.config.get("tracked_crypto", ["BTC", "ETH", "SOL"])

    @property
    def convergence_min_wallet_age_hours(self) -> int:
        return self.config.get("convergence_min_wallet_age_hours", 24)

    @property
    def tracked_categories(self) -> list:
        return self.config.get("tracked_categories", [])

    @property
    def telegram_bot_token(self) -> str:
        return self.config.get("telegram_bot_token", "")

    @property
    def telegram_chat_id(self) -> str:
        return self.config.get("telegram_chat_id", "")

    @property
    def polymarket_api_key(self) -> str:
        return self.config.get("polymarket_api_key", "")

    @property
    def polymarket_api_secret(self) -> str:
        return self.config.get("polymarket_api_secret", "")

    @property
    def polymarket_api_passphrase(self) -> str:
        return self.config.get("polymarket_api_passphrase", "")

    @property
    def leaderboard_import_interval(self) -> int:
        return self.config.get("leaderboard_import_interval", 604800)

    @property
    def domeapi_key(self) -> str:
        return self.config.get("domeapi_key", "")

    @property
    def prediedge_api_key(self) -> str:
        return self.config.get("prediedge_api_key", "")

    @property
    def jupiter_api_key(self) -> str:
        return self.config.get("jupiter_api_key", "")

    @property
    def jupiter_id(self) -> str:
        return self.config.get("jupiter_id", "")

    @property
    def polyrouter_api_key(self) -> str:
        return self.config.get("polyrouter_api_key", "")

    @property
    def quickchart_api_key(self) -> str:
        return self.config.get("quickchart_api_key", "")

    @property
    def coingecko_api_key(self) -> str:
        return self.config.get("coingecko_api_key", "")

    @property
    def cryptopanic_api_key(self) -> str:
        return self.config.get("cryptopanic_api_key", "")

    @property
    def hashdive_api_key(self) -> str:
        return self.config.get("hashdive_api_key", "")

    @property
    def bankr_api_key(self) -> str:
        return self.config.get("bankr_api_key", "")

    @property
    def trade_volume_threshold(self) -> int:
        return self.config.get("trade_volume_threshold", 1000)

    @property
    def position_size_threshold(self) -> int:
        return self.config.get("position_size_threshold", 1000)

    @property
    def min_bet_size(self) -> float:
        return self.config.get("min_bet_size", 10.0)

    @property
    def convergence_time_window_hours(self) -> int:
        return self.config.get("convergence_time_window_hours", 6)

    @property
    def convergence_max_market_age_hours(self) -> int:
        return self.config.get("convergence_max_market_age_hours", 24)

    @property
    def convergence_early_entry_minutes(self) -> int:
        return self.config.get("convergence_early_entry_minutes", 10)

    @property
    def new_market_alert_hours(self) -> int:
        return self.config.get("new_market_alert_hours", 6)

    @property
    def volume_spike_multiplier(self) -> float:
        return self.config.get("volume_spike_multiplier", 2.0)

    @property
    def odds_move_threshold(self) -> float:
        return self.config.get("odds_move_threshold", 0.15)
