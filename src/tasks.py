"""Background tasks for PolySuite."""

from apscheduler.schedulers.background import BackgroundScheduler


class TaskManager:
    """Manages background tasks."""

    def __init__(self, api_factory=None):
        """Initialize the task manager."""
        self.api_factory = api_factory
        self.scheduler = BackgroundScheduler()

    def start(self):
        """Start the task manager."""
        # No scheduled jobs by default (leaderboard import removed per user preference)
        self.scheduler.start()
        print("Task manager started.")

    def stop(self):
        """Stop the task manager."""
        self.scheduler.shutdown()
        print("Task manager stopped.")
