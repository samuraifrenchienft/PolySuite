"""Background tasks for PolySuite."""

from apscheduler.schedulers.background import BackgroundScheduler
from src.market.leaderboard import LeaderboardImporter


def refresh_leaderboard():
    """Refresh the Polymarket leaderboard."""
    print("Refreshing Polymarket leaderboard...")
    importer = LeaderboardImporter()
    importer.fetch_leaderboard()
    print("Polymarket leaderboard refreshed.")


class TaskManager:
    """Manages background tasks."""

    def __init__(self, api_factory=None):
        """Initialize the task manager."""
        self.api_factory = api_factory
        self.scheduler = BackgroundScheduler()

    def start(self):
        """Start the task manager."""
        self.scheduler.add_job(refresh_leaderboard, "interval", hours=1)
        self.scheduler.start()
        print("Task manager started.")

    def stop(self):
        """Stop the task manager."""
        self.scheduler.shutdown()
        print("Task manager stopped.")
