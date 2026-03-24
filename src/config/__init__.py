"""Configuration for PolySuite."""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any


from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Bump when DEFAULT_CONFIG vetting / discovery defaults change and existing config.json should refresh.
CONFIG_SCHEMA_VERSION = 11

DEFAULT_CONFIG = {
    "config_schema_version": CONFIG_SCHEMA_VERSION,
    "win_rate_threshold": 50.0,  # 50 = match solid wallets (~53% WR); 55 = stricter
    "min_trades_for_high_performer": 10,
    "polling_interval": 60,
    "alert_cooldown": 300,
    "tracked_wallets": [],
    "tracked_categories": [],
    "priority_categories": ["crypto", "politics"],
    "crypto_short_term_interval": 90,
    "sports_alert_interval": 120,
    "politics_alert_interval": 180,
    "kalshi_jupiter_interval": 180,
    "channel_overrides": {},
    "whale_alert_cooldown": 1200,
    "whale_check_interval": 300,
    "whale_min_size": 50000,
    "insider_min_size": 10000,
    "ai_filter_low_value_alerts": False,
    "trade_volume_threshold": 1000,
    # Alert noise reduction
    "alert_min_pnl": 500,
    "alert_skip_low_confidence": True,
    "alert_min_confidence": "MEDIUM",
    "convergence_min_volume": 5000,
    "position_size_threshold": 1000,
    "leaderboard_import_interval": 3600,  # 1 hour
    "scan_interval_sec": 180,  # Background collector: 3 min between scans (fresh data)
    "cache_ttl_sec": 0,  # 0 = always fresh; >0 = seconds to cache scan results
    "wallet_discovery_enabled": True,  # Auto-add wallets from leaderboard/insider
    "wallet_discovery_interval_sec": 1800,  # 30 min — refill leaderboard wallets faster
    "wallet_discovery_max_new": 15,  # Max new wallets per discovery run
    "wallet_discovery_max_wallets": 150,  # Cap total tracked wallets (manual + auto)
    "wallet_discovery_min_volume": 50000,  # Skip traders below this vol when leaderboard provides it; 0 = no filter
    "wallet_discovery_gamma_supplement": True,  # Merge gamma-api.polymarket.com/leaderboards (0x)
    # 0 = refresh every wallet each collector cycle; set e.g. 40 to round-robin and reduce API load
    "wallet_stats_max_per_cycle": 0,
    "wallet_cleanup_enabled": True,  # Auto-remove useless wallets (0 trades, 0 wins, low win rate)
    "wallet_cleanup_interval_sec": 3600,  # Run cleanup every hour
    "wallet_cleanup_min_win_rate": 45,  # Remove if win_rate below this (when trades >= 1)
    "wallet_cleanup_min_trades": 5,  # Require this many trades before win-rate / 0-wins removal (0 = no minimum)
    "wallet_cleanup_grace_days": 7,  # Don't remove wallets added in last N days
    "wallet_cleanup_remove_farmer": True,  # Remove wallets the classifier marks as farmers
    "wallet_cleanup_remove_bot": True,  # Remove classifier-flagged bots (requires vet confirmation below)
    "wallet_cleanup_bot_min_bot_score": 90,  # Only remove bots when vet bot_score >= this; NULL score = skip
    # Known-bad addresses — never auto-added by discovery (manual adds are unaffected)
    "wallet_blocklist": [],  # e.g. ["0xabc...", "0xdef..."]
    # Execution priority order: 1=Vetting (HIGH), 2=Alerts (MEDIUM), 3=Copy/Trade (LOW)
    # Specialty (recalibrated): category focus + profit, NOT win streak
    "vet_min_specialty_wins": 4,          # Min wins in top category within window
    "vet_min_specialty_trades": 10,       # Min trades in top category within window
    "vet_min_specialty_category_pct": 50, # Top category must be >= this % of all window trades (focus gate)
    "vet_min_specialty_profit_pct": 15,   # Reserved; not enforced (ROI shown in note only)
    "vet_specialty_window_days": 14,      # Lookback window for category stats
    "vet_max_specialty_losses": 0,        # Max losses in top category; 0 = disabled
    # Vetting pass gates (0 = disabled for numeric mins). Fee gate uses estimated_fees_paid proxy.
    "vet_min_trades_won": 0,
    "vet_max_losses": 0,
    "vet_min_pnl": 0,
    "vet_min_roi_pct": 30,  # Prefer profitable; 0 = disabled
    "vet_min_conviction": 70,  # High-conviction bettors; 0 = disabled
    "vet_min_estimated_fees": 0,
    "vet_max_trades_per_day": 100,
    "vet_min_current_win_streak": 0,
    "vet_min_reliability_score": 0,
    "win_streak_badge_threshold": 5,
    "farming_min_profit_pct": 5,
    "farming_zero_weight_below_pct": 2,
    "farming_penalty_pct": 20,
    "farming_score_cap": 60,
    "farming_avg_profit_pct_min": 5,
    # Copy/execution removed: pure wallet finder (no copy trading)
    "copy_removed": True,
    "copy_enabled": False,
    # Vetting UI / hot-streak (used by WalletVetting; kept in file on schema upgrade)
    "vet_recent_wins_window": 10,
    "vet_min_recent_wins": 3,
    # Overrides for known-good wallets when API resolution is thin
    "vet_min_resolved_markets": 0,  # 0 = skip gate; 5 = require 5+ resolved markets
    "vet_max_bot_score": 70,  # Fail vetting if bot_score > this; lower = stricter; 100 = off
    # Unresolved losses: only count when market resolution date is days past + wallet holds losing position
    # 0 = disable gate (can't reliably track); >0 = max allowed before fail
    "vet_max_unresolved_losses": 0,
    "vet_unresolved_min_days_past": 3,  # Only count if endDate is this many days past (avoids false positives)
    # Background collector: skip stats refresh if last_updated is newer than this (hours). 0 = refresh all.
    "collector_stats_skip_hours": 24,
    # Dashboard bulk Classify: skip if last_scored_at within this many hours. 0 = classify all.
    "classify_bulk_skip_hours": 24,
    # Bulk Vet All: skip if last_vetted_at within this many hours (e.g. 48–72 when vetting 4×/day). 0 = vet all.
    "vet_skip_hours": 48,
    # Dashboard UI: poll /api/dashboard/data this often (seconds). 0 = manual refresh only.
    "dashboard_poll_interval_sec": 90,
}

# Keys reset from DEFAULT_CONFIG when config.json is older than CONFIG_SCHEMA_VERSION.
_VETTING_AND_WALLET_PIPELINE_KEYS = tuple(
    k
    for k in DEFAULT_CONFIG
    if k.startswith("vet_")
    or k
    in (
        "wallet_cleanup_enabled",
        "wallet_cleanup_interval_sec",
        "wallet_cleanup_min_win_rate",
        "wallet_cleanup_min_trades",
        "wallet_cleanup_grace_days",
        "wallet_cleanup_remove_farmer",
        "wallet_cleanup_remove_bot",
        "wallet_cleanup_bot_min_bot_score",
        "wallet_blocklist",
        "wallet_discovery_enabled",
        "wallet_discovery_interval_sec",
        "wallet_discovery_max_new",
        "wallet_discovery_max_wallets",
        "wallet_discovery_min_volume",
        "wallet_discovery_gamma_supplement",
        "win_rate_threshold",  # high-performer / discovery alignment
        "collector_stats_skip_hours",
        "classify_bulk_skip_hours",
    )
)

# Shared Bankr client instance
_bankr_client = None


def get_bankr_client(api_key: str = None) -> "BankrClient":
    """Get or create shared Bankr client."""
    global _bankr_client
    if _bankr_client is None and api_key:
        from src.market.bankr import BankrClient

        _bankr_client = BankrClient(api_key)
        return _bankr_client


def max_tracked_wallets(config: Any = None) -> int:
    """Max wallets for CLI, Discord, and manual adds (same cap as auto wallet discovery)."""
    default_cap = int(DEFAULT_CONFIG.get("wallet_discovery_max_wallets", 100) or 100)
    if config is None:
        return default_cap
    if isinstance(config, dict):
        return int(config.get("wallet_discovery_max_wallets", default_cap) or default_cap)
    return int(config.get("wallet_discovery_max_wallets", default_cap) or default_cap)


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
    "DASHBOARD_API_KEY",
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
        loaded_from_file: Dict[str, Any] = {}
        file_existed = Path(self.config_path).exists()

        # Load from config.json for non-secret values
        if file_existed:
            try:
                with open(self.config_path, "r") as f:
                    loaded_from_file = json.load(f)
                    # Strip PumpFun keys (feature removed)
                    pump_keys = [k for k in loaded_from_file if str(k).startswith("pump_")]
                    for k in pump_keys:
                        del loaded_from_file[k]
                    if pump_keys:
                        try:
                            with open(self.config_path, "w", encoding="utf-8") as fw:
                                json.dump(loaded_from_file, fw, indent=2)
                            logger.info("Removed %d pump_* keys from config (PumpFun removed)", len(pump_keys))
                        except OSError:
                            pass
                    config.update(loaded_from_file)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Error loading config file: %s — using defaults for non-secrets", e)

        # One-time (per schema) refresh: old config.json often had strict vet_* / cleanup on disk.
        old_schema = int(loaded_from_file.get("config_schema_version") or 0)
        if file_existed and old_schema < CONFIG_SCHEMA_VERSION:
            for key in _VETTING_AND_WALLET_PIPELINE_KEYS:
                if key in DEFAULT_CONFIG:
                    config[key] = DEFAULT_CONFIG[key]
            config["config_schema_version"] = CONFIG_SCHEMA_VERSION
            try:
                # Do not persist env-only secrets (not in file yet at this point in _load).
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                logger.info(
                    "config.json upgraded to schema %s (vetting & wallet pipeline keys synced from defaults)",
                    CONFIG_SCHEMA_VERSION,
                )
            except OSError as e:
                logger.warning(
                    "Could not save config.json after schema upgrade (%s); using merged values in memory only",
                    e,
                )

        # Renamed vet_bulk_skip_hours → classify_bulk_skip_hours + collector_stats_skip_hours (schema 11)
        if "vet_bulk_skip_hours" in loaded_from_file:
            try:
                vbi = int(loaded_from_file.get("vet_bulk_skip_hours", 24) or 0)
            except (TypeError, ValueError):
                vbi = 24
            config["classify_bulk_skip_hours"] = vbi
            config["collector_stats_skip_hours"] = vbi
        config.pop("vet_bulk_skip_hours", None)

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

    def reload(self) -> None:
        """Reload merged config from disk (`config.json`) and environment.

        Used by the dashboard so edits to `config.json` apply without restarting
        the server (collector intervals still require restart for `main.py run`).
        """
        self.config = self._load()

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
    def ai_filter_low_value_alerts(self) -> bool:
        """Skip new market alerts when AI scores opportunity as LOW and volume < 5k."""
        return self.config.get("ai_filter_low_value_alerts", False)

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
    def scan_interval_sec(self) -> int:
        """Seconds between background collector runs (default 30 min)."""
        return self.config.get("scan_interval_sec", 1800)

    @property
    def cache_ttl_sec(self) -> int:
        """Cache TTL for scan results in seconds (default 10 min)."""
        return self.config.get("cache_ttl_sec", 600)

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

    @property
    def vet_recent_wins_window(self) -> int:
        return self.config.get("vet_recent_wins_window", 10)

    @property
    def vet_min_recent_wins(self) -> int:
        return self.config.get("vet_min_recent_wins", 3)

    @property
    def vet_min_specialty_wins(self) -> int:
        return self.config.get("vet_min_specialty_wins", 4)

    @property
    def vet_min_specialty_trades(self) -> int:
        return self.config.get("vet_min_specialty_trades", 10)

    @property
    def vet_min_specialty_category_pct(self) -> int:
        return self.config.get("vet_min_specialty_category_pct", 50)

    @property
    def vet_min_specialty_profit_pct(self) -> int:
        return self.config.get("vet_min_specialty_profit_pct", 15)

    @property
    def vet_specialty_window_days(self) -> int:
        return self.config.get("vet_specialty_window_days", 14)

    @property
    def vet_max_specialty_losses(self) -> int:
        return self.config.get("vet_max_specialty_losses", 2)

    @property
    def win_streak_badge_threshold(self) -> int:
        return self.config.get("win_streak_badge_threshold", 5)

    @property
    def farming_min_profit_pct(self) -> float:
        return self.config.get("farming_min_profit_pct", 5)

    @property
    def farming_zero_weight_below_pct(self) -> float:
        return self.config.get("farming_zero_weight_below_pct", 2)

    @property
    def farming_penalty_pct(self) -> float:
        return self.config.get("farming_penalty_pct", 20)

    @property
    def farming_score_cap(self) -> float:
        return self.config.get("farming_score_cap", 60)

    @property
    def farming_avg_profit_pct_min(self) -> float:
        return self.config.get("farming_avg_profit_pct_min", 5)

    @property
    def vet_min_pnl(self) -> int:
        return self.config.get("vet_min_pnl", 0)

    @property
    def vet_max_trades_per_day(self) -> int:
        return self.config.get("vet_max_trades_per_day", 100)

    @property
    def vet_min_roi_pct(self) -> int:
        return self.config.get("vet_min_roi_pct", 0)

    @property
    def vet_min_conviction(self) -> int:
        return self.config.get("vet_min_conviction", 0)

    @property
    def vet_min_trades_won(self) -> int:
        return self.config.get("vet_min_trades_won", 0)

    @property
    def vet_max_losses(self) -> int:
        return self.config.get("vet_max_losses", 0)

    @property
    def vet_min_current_win_streak(self) -> int:
        return self.config.get("vet_min_current_win_streak", 0)

    @property
    def vet_min_reliability_score(self) -> int:
        return self.config.get("vet_min_reliability_score", 0)

    @property
    def vet_min_estimated_fees(self) -> int:
        return self.config.get("vet_min_estimated_fees", 0)
