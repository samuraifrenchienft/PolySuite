"""Copy target storage - wallets to copy trade from.

Persists to data/copy_targets.json. Structure: {address, nickname, added_at, sizing_mode, size_value}.
Separate from tracked wallets. Prepared for multi-user migration (DB schema later).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.utils import is_valid_eth_address


COPY_TARGETS_PATH = "data/copy_targets.json"
MAX_COPY_TARGETS = 20


def _load_targets() -> List[dict]:
    """Load copy targets from JSON file."""
    path = Path(COPY_TARGETS_PATH)
    if not path.exists():
        return []
    try:
        with path.open() as f:
            data = json.load(f)
        return data.get("targets", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_targets(targets: List[dict]) -> None:
    """Save copy targets to JSON file."""
    path = Path(COPY_TARGETS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"updated": datetime.utcnow().isoformat(), "targets": targets}
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def add_copy_target(address: str, nickname: str = "") -> bool:
    """Add wallet to copy targets. Returns False if invalid, already exists, or limit reached."""
    address = address.strip().lower()
    if not address:
        return False
    if not is_valid_eth_address(address):
        return False
    targets = _load_targets()
    if any(t.get("address", "").lower() == address for t in targets):
        return False
    if len(targets) >= MAX_COPY_TARGETS:
        return False
    nick = (nickname or address[:12] + "...").strip()[:32]
    targets.append({
        "address": address,
        "nickname": nick,
        "added_at": datetime.utcnow().isoformat(),
        "sizing_mode": "multiplier",
        "size_value": 1.0,
    })
    _save_targets(targets)
    return True


def remove_copy_target(address: str) -> bool:
    """Remove wallet from copy targets."""
    address = address.strip().lower()
    targets = _load_targets()
    before = len(targets)
    targets = [t for t in targets if t.get("address", "").lower() != address]
    if len(targets) == before:
        return False
    _save_targets(targets)
    return True


def list_copy_targets() -> List[dict]:
    """List all copy targets."""
    return _load_targets()


def get_copy_target_addresses() -> List[str]:
    """Return list of valid addresses (lowercase) for CopyEngine filter.
    Filters out any legacy invalid entries."""
    return [
        addr
        for t in _load_targets()
        if (addr := (t.get("address") or "").strip().lower())
        and is_valid_eth_address(addr)
    ]
