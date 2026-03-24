"""Centralized paths for PolySuite.

All storage paths should be imported from here to ensure consistency.
"""

import os

# Project root (parent of src/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Data directory
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

# Primary SQLite database (wallets, scoring, tier log, credentials)
DB_PATH = os.path.join(DATA_DIR, "polysuite.db")

# Copy targets (JSON) - used when copy_removed=False
COPY_TARGETS_PATH = os.path.join(DATA_DIR, "copy_targets.json")


def ensure_data_dir() -> str:
    """Create data directory if missing. Returns DATA_DIR."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR
