"""Tests for copy target storage (add, remove, list, get_addresses)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.copy import storage


@pytest.fixture
def temp_copy_targets():
    """Use temp dir for copy_targets.json to avoid polluting data/."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "copy_targets.json"
        with patch.object(storage, "COPY_TARGETS_PATH", str(path)):
            yield path


def test_add_copy_target_success(temp_copy_targets):
    """Add valid address succeeds."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        ok = storage.add_copy_target("0x1234567890abcdef1234567890abcdef12345678", "Alpha")
        assert ok is True
        targets = storage.list_copy_targets()
        assert len(targets) == 1
        assert targets[0]["address"] == "0x1234567890abcdef1234567890abcdef12345678"
        assert targets[0]["nickname"] == "Alpha"


def test_add_copy_target_with_empty_nickname_uses_address_prefix(temp_copy_targets):
    """Empty nickname uses address[:12] + '...'."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        storage.add_copy_target("0xabcdef1234567890abcdef1234567890abcdef12")
        targets = storage.list_copy_targets()
        assert targets[0]["nickname"] == "0xabcdef1234..."


def test_add_copy_target_duplicate_returns_false(temp_copy_targets):
    """Adding same address again returns False."""
    addr = "0x1234567890abcdef1234567890abcdef12345678"
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        storage.add_copy_target(addr)
        ok = storage.add_copy_target(addr)
        assert ok is False
        assert len(storage.list_copy_targets()) == 1


def test_add_copy_target_empty_address_returns_false(temp_copy_targets):
    """Empty or whitespace address returns False."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        assert storage.add_copy_target("") is False
        assert storage.add_copy_target("   ") is False


def test_add_copy_target_limit_reached(temp_copy_targets):
    """Adding beyond MAX_COPY_TARGETS returns False."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        with patch.object(storage, "MAX_COPY_TARGETS", 2):
            storage.add_copy_target("0x1111111111111111111111111111111111111111")
            storage.add_copy_target("0x2222222222222222222222222222222222222222")
            ok = storage.add_copy_target("0x3333333333333333333333333333333333333333")
            assert ok is False
            assert len(storage.list_copy_targets()) == 2


def test_remove_copy_target_success(temp_copy_targets):
    """Remove existing address succeeds."""
    addr = "0x1234567890abcdef1234567890abcdef12345678"
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        storage.add_copy_target(addr)
        ok = storage.remove_copy_target(addr)
        assert ok is True
        assert len(storage.list_copy_targets()) == 0


def test_remove_copy_target_nonexistent_returns_false(temp_copy_targets):
    """Remove non-existent address returns False."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        ok = storage.remove_copy_target("0x0000000000000000000000000000000000000001")
        assert ok is False


def test_get_copy_target_addresses_returns_lowercase(temp_copy_targets):
    """get_copy_target_addresses returns lowercase addresses."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        storage.add_copy_target("0xabcdef1234567890abcdef1234567890abcdef12")
        addrs = storage.get_copy_target_addresses()
        assert addrs == ["0xabcdef1234567890abcdef1234567890abcdef12"]


def test_list_copy_targets_empty_when_no_file(temp_copy_targets):
    """list_copy_targets returns [] when file doesn't exist."""
    path = temp_copy_targets
    if path.exists():
        path.unlink()
    with patch.object(storage, "COPY_TARGETS_PATH", str(path)):
        assert storage.list_copy_targets() == []


def test_add_copy_target_rejects_invalid_address(temp_copy_targets):
    """Storage rejects invalid addresses (defense-in-depth)."""
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        ok = storage.add_copy_target("not-an-eth-address")
        assert ok is False
        assert storage.list_copy_targets() == []


def test_get_copy_target_addresses_filters_invalid_legacy(temp_copy_targets):
    """get_copy_target_addresses excludes invalid addresses (legacy data)."""
    valid = "0x1234567890abcdef1234567890abcdef12345678"
    with patch.object(storage, "COPY_TARGETS_PATH", str(temp_copy_targets)):
        storage.add_copy_target(valid)
        # Manually inject invalid entry (simulate legacy data)
        targets = storage.list_copy_targets()
        targets.append({"address": "garbage", "nickname": "x", "added_at": "2020-01-01"})
        temp_copy_targets.write_text(
            '{"updated":"2020-01-01","targets":'
            + json.dumps(targets)
            + "}"
        )
        addrs = storage.get_copy_target_addresses()
        assert addrs == [valid]
