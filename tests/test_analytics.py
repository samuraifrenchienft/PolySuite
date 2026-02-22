"""Tests for the analytics module."""
import pytest
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.analytics.smart_money import SmartMoneyDetector


@pytest.fixture
def mock_clients(mocker):
    """Mock the API clients."""
    mocker.patch('src.analytics.smart_money.PolyScopeClient', autospec=True)
    mocker.patch('src.analytics.smart_money.PrediedgeClient', autospec=True)
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', autospec=True)


def test_identify_smart_money_from_all_sources(mocker, mock_clients):
    """Test identifying smart money from all sources."""
    # Mock the return values of the API clients
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = [{"address": "0x1"}, {"address": "0x2"}]
    mocker.patch('src.analytics.smart_money.PolyScopeClient', return_value=mock_polyscope)

    mock_prediedge = MagicMock()
    mock_prediedge.get_whale_wallets.return_value = [{"address": "0x3"}, {"address": "0x4"}]
    mocker.patch('src.analytics.smart_money.PrediedgeClient', return_value=mock_prediedge)

    mock_leaderboard = MagicMock()
    mock_leaderboard.import_all_polymarket.return_value = [{"address": "0x5"}, {"address": "0x6"}]
    mock_leaderboard.get_wallet_stats.side_effect = [
        {"total_trades": 100, "win_rate": 0.7},
        {"total_trades": 100, "win_rate": 0.8},
    ]
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', return_value=mock_leaderboard)

    detector = SmartMoneyDetector()
    smart_wallets = detector.identify_smart_money()

    assert set(smart_wallets) == {"0x1", "0x2", "0x3", "0x4", "0x5", "0x6"}


def test_identify_smart_money_with_empty_responses(mocker, mock_clients):
    """Test identifying smart money with empty responses from APIs."""
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = []
    mocker.patch('src.analytics.smart_money.PolyScopeClient', return_value=mock_polyscope)

    mock_prediedge = MagicMock()
    mock_prediedge.get_whale_wallets.return_value = []
    mocker.patch('src.analytics.smart_money.PrediedgeClient', return_value=mock_prediedge)

    mock_leaderboard = MagicMock()
    mock_leaderboard.import_all_polymarket.return_value = []
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', return_value=mock_leaderboard)

    detector = SmartMoneyDetector()
    smart_wallets = detector.identify_smart_money()

    assert smart_wallets == []


def test_identify_smart_money_with_duplicates(mocker, mock_clients):
    """Test identifying smart money with duplicate addresses."""
    mock_polyscope = MagicMock()
    mock_polyscope.get_smart_traders.return_value = [{"address": "0x1"}, {"address": "0x2"}]
    mocker.patch('src.analytics.smart_money.PolyScopeClient', return_value=mock_polyscope)

    mock_prediedge = MagicMock()
    mock_prediedge.get_whale_wallets.return_value = [{"address": "0x2"}, {"address": "0x3"}]
    mocker.patch('src.analytics.smart_money.PrediedgeClient', return_value=mock_prediedge)

    mock_leaderboard = MagicMock()
    mock_leaderboard.import_all_polymarket.return_value = [{"address": "0x3"}, {"address": "0x4"}]
    mock_leaderboard.get_wallet_stats.side_effect = [
        {"total_trades": 100, "win_rate": 0.7},
        {"total_trades": 100, "win_rate": 0.8},
    ]
    mocker.patch('src.analytics.smart_money.LeaderboardImporter', return_value=mock_leaderboard)

    detector = SmartMoneyDetector()
    smart_wallets = detector.identify_smart_money()

    assert set(smart_wallets) == {"0x1", "0x2", "0x3", "0x4"}
