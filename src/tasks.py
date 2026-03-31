"""Background tasks for PolySuite."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from src.market.leaderboard import LeaderboardImporter
from src.market.api import APIClientFactory
from src.analytics.scan_results_storage import ScanResultsStorage

logger = logging.getLogger(__name__)


def refresh_leaderboard(api_factory: APIClientFactory):
    """Refresh the Polymarket leaderboard."""
    logger.info("Refreshing Polymarket leaderboard...")
    importer = LeaderboardImporter(api_factory)
    importer.import_all_polymarket()
    logger.info("Polymarket leaderboard refreshed.")


def emit_strategy_digest(hours: int = 24):
    """Build and log a compact strategy digest (analytics plumbing scaffold)."""
    try:
        storage = ScanResultsStorage()
        digest = storage.build_digest_text(hours=hours)
        logger.info("[Digest]\n%s", digest)
    except Exception as e:
        logger.warning("Strategy digest failed: %s", e)

class TaskManager:
    """Manages background tasks."""

    def __init__(self, api_factory: APIClientFactory, config=None):
        """Initialize the task manager."""
        self.scheduler = BackgroundScheduler()
        self.api_factory = api_factory
        self.config = config

    def start(self):
        """Start the task manager."""
        self.scheduler.add_job(refresh_leaderboard, "interval", hours=1, args=[self.api_factory])
        digest_enabled = bool(getattr(self.config, "get", lambda *_: False)("alert_digest_enabled", False)) if self.config else False
        digest_hours = int(getattr(self.config, "get", lambda *_: 24)("alert_digest_interval_hours", 24)) if self.config else 24
        if digest_enabled:
            self.scheduler.add_job(
                emit_strategy_digest,
                "interval",
                hours=max(1, digest_hours),
                args=[max(1, digest_hours)],
            )
        self.scheduler.start()
        logger.info("Task manager started.")
