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
    "priority_categories": ["crypto", "politics"],
    "crypto_short_term_interval": 90,
    "sports_alert_interval": 240,  # 4 min (reduced noise)
    "politics_alert_interval": 300,  # 5 min (reduced noise)
    "kalshi_jupiter_interval": 180,
    "channel_overrides": {},
    "whale_alert_cooldown": 1200,
    "whale_check_interval": 300,
    "whale_min_size": 50000,
    "whale_alerts_enabled": False,  # Disabled until curated AI-vetted wallet list
    "insider_signal_enabled": True,  # High priority: fresh wallet + large trade + winning
    "insider_signal_interval": 300,  # 5 min
    "insider_signal_min_trade_usd": 5000,
    "insider_signal_fresh_max_trades": 10,
    "weird_wallet_liquidity_threshold": 0.02,  # Flag size anomaly if trade > 2% of order book
    "weird_wallet_niche_volume_max": 50000,  # Flag niche market if volume < $50k
    "contrarian_alerts_enabled": False,  # Long-shot: high vol one side, high payout other
    "contrarian_interval": 600,  # 10 min
    "contrarian_min_volume": 10000,
    "contrarian_min_imbalance": 0.6,
    "contrarian_payout_min": 0.20,
    "contrarian_payout_max": 0.40,
    "trend_scanner_enabled": False,  # Deprioritized - meme coins, different use case
    "ai_daily_summary_enabled": False,  # Deprioritized - overlaps with 30-min report
    "jupiter_alerts_enabled": True,  # Jupiter prediction market alerts (set False if geo-restricted)
    "ai_filter_low_value_alerts": True,
    "ai_report_enabled": True,
    "min_volume_for_alert": 5000,
    "qualification_strict_mode": False,
    "min_liquidity_depth_usd": 5000,
    "max_spread_pct": 5.0,
    "require_liquidity_check": False,
    "trade_volume_threshold": 1000,
    "position_size_threshold": 1000,
    "leaderboard_import_interval": 3600,  # 1 hour
    "background_vetting_interval": 86400,  # 24 hours - vet leaderboard in background
    "vet_min_pnl": 0,  # Minimum realized PnL (USD) to qualify as vetted
    "vet_min_roi_pct": 0,  # Minimum ROI % (0 = no filter initially)
    "vet_max_trades_per_day": 100,  # Reject arbitrage-like frequency
    "vet_min_conviction": 0,  # Minimum conviction score 0-100 (0 = no filter)
    "vet_min_recent_wins": 3,  # Min wins in last N resolved trades to qualify via recent-wins path
    "vet_recent_wins_window": 10,  # Look at last N resolved trades for recent-wins
    "vet_min_specialty_wins": 3,  # Min wins in a market to qualify as specialty
    "vet_min_specialty_streak": 2,  # Min wins in a row in that market
    "vet_max_specialty_losses": 1,  # Max losses in that market for specialty (low losses)
    "vet_min_estimated_fees": 0,  # Min estimated fees paid (Polymarket only; Kalshi/Jupiter bypass)
    "vet_min_trades_won": 5,  # Min total wins in resolved markets
    "vet_max_losses": 0,  # Max total losses allowed (0 = no limit)
    "wallet_list_interval": 604800,  # Weekly (7 days) - seconds between wallet list broadcasts
    "wallet_list_min": 10,  # Min wallets to include in weekly list
    "wallet_list_max": 30,  # Max wallets in weekly list
    # Copy trading (Phase D)
    "copy_enabled": False,
    "copy_size_multiplier": 1.0,
    "copy_max_order_usd": 100,
    "copy_min_odds": 0.05,
    "copy_max_odds": 0.95,
    "copy_min_liquidity_usd": 2000,
    "copy_pause": False,
    "copy_dry_run": True,
    "copy_default_user_id": "",  # Discord/Telegram user ID for copy execution (optional)
    # Safety controls
    "copy_max_trades_per_minute": 0,  # 0 = no throttle
    "copy_reduce_multiplier_after_trades": 0,  # 0 = disabled; after N trades in window, use reduced multiplier
    "copy_reduced_multiplier": 0.5,
    "copy_reduction_window_minutes": 60,
    "copy_freeze_after_trades": 0,  # 0 = disabled; freeze new positions after N trades in window
    "copy_freeze_duration_minutes": 60,
    "copy_fee_pct": 0.77,  # Fee % on copy trades (future monetization)
    "copy_referral_discount_pct": 10,  # Referral discount % (future)
}

# Shared Bankr client instance
_bankr_client = None


def get_bankr_client(api_key: str = None) -> "BankrClient | None":
    """Get or create shared Bankr client. Returns None if api_key is empty or unset.
    Callers must guard: if not bankr or not bankr.is_configured(): ..."""
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
    "discord_alerts_webhook_url",  # For trading alerts
    "discord_trends_webhook_url",  # For trend alerts
    "telegram_bot_token",
    "telegram_chat_id",
    "telegram_health_chat_id",
    "telegram_alerts_chat_id",  # For trading alerts
    "telegram_trends_chat_id",  # For trend alerts
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

        # Env overrides for copy trading
        if os.getenv("COPY_DEFAULT_USER_ID"):
            config["copy_default_user_id"] = os.getenv("COPY_DEFAULT_USER_ID").strip()

        # MED-001: Warn if secrets came from file (config.json) instead of env
        if os.getenv("POLYSUITE_STRICT_SECRETS", "").lower() in ("1", "true", "yes"):
            for key in SECRET_KEYS:
                if config.get(key) and not os.getenv(key.upper()):
                    raise RuntimeError(
                        f"Secret '{key}' loaded from config.json but POLYSUITE_STRICT_SECRETS=1. "
                        "Set secrets via environment variables only."
                    )

        return config

    def save(self) -> None:
        """Save config to file."""
        # Only save non-secret keys
        config_to_save = {
            k: v for k, v in self.config.items() if k not in SECRET_KEYS
        }
        with open(self.config_path, "w") as f:
            json.dump(config_to_save, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value."""
        return self.config.get(key, default)

    def get_safe_for_logging(self) -> Dict[str, Any]:
        """Return config with secrets redacted (HIGH-002). Use for logging/debug."""
        return {
            k: ("***" if k in SECRET_KEYS else v)
            for k, v in self.config.items()
        }

    def __repr__(self) -> str:
        """Avoid leaking secrets when config is printed or logged (SEC-003)."""
        return repr(self.get_safe_for_logging())

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
    def discord_alerts_webhook_url(self) -> str:
        return self.config.get("discord_alerts_webhook_url", "")

    @property
    def discord_trends_webhook_url(self) -> str:
        return self.config.get("discord_trends_webhook_url", "")

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
    def priority_categories(self) -> list:
        return self.config.get("priority_categories", ["crypto", "politics"])

    @property
    def crypto_short_term_interval(self) -> int:
        return self.config.get("crypto_short_term_interval", 90)

    @property
    def sports_alert_interval(self) -> int:
        return self.config.get("sports_alert_interval", 120)

    @property
    def politics_alert_interval(self) -> int:
        return self.config.get("politics_alert_interval", 180)

    @property
    def kalshi_jupiter_interval(self) -> int:
        return self.config.get("kalshi_jupiter_interval", 180)

    @property
    def channel_overrides(self) -> dict:
        """Override channels per category, e.g. {'crypto': {'discord_webhook_url': '...', 'telegram_chat_id': '...'}}."""
        return self.config.get("channel_overrides", {})

    @property
    def whale_alert_cooldown(self) -> int:
        """Seconds between whale alerts (default 20 min)."""
        return self.config.get("whale_alert_cooldown", 1200)

    @property
    def whale_check_interval(self) -> int:
        """Seconds between whale position checks (default 5 min)."""
        return self.config.get("whale_check_interval", 300)

    @property
    def whale_min_size(self) -> float:
        """Minimum trade size ($) to count as whale (default 50k)."""
        return self.config.get("whale_min_size", 50000)

    @property
    def whale_alerts_enabled(self) -> bool:
        """Enable whale trade alerts (disabled until curated AI-vetted wallet list)."""
        return self.config.get("whale_alerts_enabled", False)

    @property
    def trend_scanner_enabled(self) -> bool:
        """Enable trend scanner (pump.fun, meme coins)."""
        return self.config.get("trend_scanner_enabled", False)

    @property
    def ai_daily_summary_enabled(self) -> bool:
        """Enable AI daily summary (overlaps with 30-min report)."""
        return self.config.get("ai_daily_summary_enabled", False)

    @property
    def jupiter_alerts_enabled(self) -> bool:
        """Enable Jupiter prediction market alerts (Polymarket-sourced)."""
        return self.config.get("jupiter_alerts_enabled", False)

    @property
    def background_vetting_interval(self) -> int:
        """Seconds between background leaderboard vetting runs (default 24h)."""
        return self.config.get("background_vetting_interval", 86400)

    @property
    def ai_filter_low_value_alerts(self) -> bool:
        """Skip new market alerts when AI scores opportunity as LOW and volume < 5k."""
        return self.config.get("ai_filter_low_value_alerts", False)

    @property
    def ai_report_enabled(self) -> bool:
        """Enable AI 30-min market report."""
        return self.config.get("ai_report_enabled", True)

    @property
    def min_liquidity_depth_usd(self) -> float:
        """Minimum order book depth (USD) for alert qualification."""
        return float(self.config.get("min_liquidity_depth_usd", 5000))

    @property
    def max_spread_pct(self) -> float:
        """Maximum spread (percent) for alert qualification."""
        return float(self.config.get("max_spread_pct", 5.0))

    @property
    def require_liquidity_check(self) -> bool:
        """Require liquidity depth check before sending new market alerts."""
        return self.config.get("require_liquidity_check", False)

    @property
    def min_volume_for_alert(self) -> float:
        """Minimum market volume for new market alerts."""
        return float(self.config.get("min_volume_for_alert", 5000))

    @property
    def qualification_strict_mode(self) -> bool:
        """Reject on any qualification gate failure."""
        return self.config.get("qualification_strict_mode", False)

    @property
    def telegram_bot_token(self) -> str:
        return self.config.get("telegram_bot_token", "")

    @property
    def telegram_chat_id(self) -> str:
        return self.config.get("telegram_chat_id", "")

    @property
    def telegram_health_chat_id(self) -> str:
        return self.config.get("telegram_health_chat_id", "")

    @property
    def telegram_alerts_chat_id(self) -> str:
        return self.config.get("telegram_alerts_chat_id", "")

    @property
    def telegram_trends_chat_id(self) -> str:
        return self.config.get("telegram_trends_chat_id", "")

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
    def vet_min_pnl(self) -> float:
        """Minimum realized PnL (USD) to qualify as vetted."""
        return float(self.config.get("vet_min_pnl", 0))

    @property
    def vet_min_roi_pct(self) -> float:
        """Minimum ROI % to qualify (0 = no filter)."""
        return float(self.config.get("vet_min_roi_pct", 0))

    @property
    def vet_max_trades_per_day(self) -> float:
        """Reject arbitrage-like wallets above this trades/day."""
        return float(self.config.get("vet_max_trades_per_day", 100))

    @property
    def vet_min_conviction(self) -> float:
        """Minimum conviction score 0-100 (0 = no filter)."""
        return float(self.config.get("vet_min_conviction", 0))

    @property
    def vet_min_recent_wins(self) -> int:
        """Min wins in last N resolved trades to qualify via recent-wins path."""
        return int(self.config.get("vet_min_recent_wins", 3))

    @property
    def vet_recent_wins_window(self) -> int:
        """Look at last N resolved trades for recent-wins."""
        return int(self.config.get("vet_recent_wins_window", 10))

    @property
    def vet_min_specialty_wins(self) -> int:
        """Min wins in a market to qualify as specialty."""
        return int(self.config.get("vet_min_specialty_wins", 3))

    @property
    def vet_min_specialty_streak(self) -> int:
        """Min wins in a row in that market for specialty."""
        return int(self.config.get("vet_min_specialty_streak", 2))

    @property
    def vet_max_specialty_losses(self) -> int:
        """Max losses in that market for specialty (low losses)."""
        return int(self.config.get("vet_max_specialty_losses", 1))

    @property
    def vet_min_estimated_fees(self) -> float:
        """Min estimated fees paid (Polymarket only; Kalshi/Jupiter bypass)."""
        return float(self.config.get("vet_min_estimated_fees", 0))

    @property
    def vet_min_trades_won(self) -> int:
        """Min total wins in resolved markets."""
        return int(self.config.get("vet_min_trades_won", 5))

    @property
    def vet_max_losses(self) -> int:
        """Max total losses allowed (0 = no limit)."""
        return int(self.config.get("vet_max_losses", 0))

    @property
    def wallet_list_interval(self) -> int:
        """Seconds between weekly wallet list broadcasts (default 7 days)."""
        return int(self.config.get("wallet_list_interval", 604800))

    @property
    def wallet_list_min(self) -> int:
        """Minimum wallets to include in weekly list."""
        return int(self.config.get("wallet_list_min", 10))

    @property
    def wallet_list_max(self) -> int:
        """Maximum wallets in weekly list."""
        return int(self.config.get("wallet_list_max", 30))

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
