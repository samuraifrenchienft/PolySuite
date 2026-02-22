"""Tests for the analytics module."""
import pytest
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analytics.smart_money import SmartMoneyDetector


@pytest.fixture
def mock_api_factory():
    """Mock the API factory."""
    mock_factory = MagicMock()
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = [{"address": "0x1"}, {"address": "0x2"}]
    mock_factory.get_polyscope_client.return_value = mock_polyscope
    return mock_factory


def test_identify_smart_money_from_all_sources(mocker, mock_api_factory):
    """Test identifying smart money from all sources."""
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = [{"address": "0x1"}, {"address": "0x2"}]
    mock_api_factory.get_polyscope_client.return_value = mock_polyscope

    mock_leaderboard = MagicMock()
    mock_leaderboard.fetch_leaderboard.return_value = [
        {"address": "0x5"},
        {"address": "0x6"},
    ]
    mock_leaderboard.get_wallet_stats.side_effect = [
        {"total_trades": 100, "win_rate": 0.7},
        {"total_trades": 100, "win_rate": 0.8},
    ]
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', return_value=mock_leaderboard)

    detector = SmartMoneyDetector(mock_api_factory)
    smart_wallets = detector.identify_smart_money()

    assert set(smart_wallets) == {"0x1", "0x2", "0x5", "0x6"}


def test_identify_smart_money_with_empty_responses(mocker, mock_api_factory):
    """Test identifying smart money with empty responses from APIs."""
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = []
    mock_api_factory.get_polyscope_client.return_value = mock_polyscope

    mock_leaderboard = MagicMock()
    mock_leaderboard.fetch_leaderboard.return_value = []
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', return_value=mock_leaderboard)

    detector = SmartMoneyDetector(mock_api_factory)
    smart_wallets = detector.identify_smart_money()

    assert smart_wallets == []


def test_identify_smart_money_with_duplicates(mocker, mock_api_factory):
    """Test identifying smart money with duplicate addresses."""
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = [{"address": "0x1"}, {"address": "0x2"}]
    mock_api_factory.get_polyscope_client.return_value = mock_polyscope

    mock_leaderboard = MagicMock()
    mock_leaderboard.fetch_leaderboard.return_value = [{"address": "0x2"}, {"address": "0x3"}]
    mock_leaderboard.get_wallet_stats.side_effect = [
        {"total_trades": 100, "win_rate": 0.7},
        {"total_trades": 100, "win_rate": 0.8},
    ]
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', return_value=mock_leaderboard)

    detector = SmartMoneyDetector(mock_api_factory)
    smart_wallets = detector.identify_smart_money()

    assert set(smart_wallets) == {"0x1", "0x2", "0x3"}
