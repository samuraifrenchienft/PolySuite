"""Copy trading module."""

from src.copy.storage import (
    add_copy_target,
    remove_copy_target,
    list_copy_targets,
    get_copy_target_addresses,
)
from src.copy.engine import CopyEngine

__all__ = [
    "add_copy_target",
    "remove_copy_target",
    "list_copy_targets",
    "get_copy_target_addresses",
    "CopyEngine",
]
