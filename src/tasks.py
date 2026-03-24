"""Background tasks for PolySuite."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from src.market.leaderboard import LeaderboardImporter
from src.market.api import APIClientFactory

logger = logging.getLogger(__name__)


def refresh_leaderboard(api_factory: APIClientFactory):
    """Refresh the Polymarket leaderboard."""
    logger.info("Refreshing Polymarket leaderboard...")
    importer = LeaderboardImporter(api_factory)
    importer.import_all_polymarket()
    logger.info("Polymarket leaderboard refreshed.")

class TaskManager:
    """Manages background tasks."""

    def __init__(self, api_factory: APIClientFactory):
        """Initialize the task manager."""
        self.scheduler = BackgroundScheduler()
        self.api_factory = api_factory

    def start(self):
        """Start the task manager."""
        self.scheduler.add_job(refresh_leaderboard, "interval", hours=1, args=[self.api_factory])
        self.scheduler.start()
        logger.info("Task manager started.")
