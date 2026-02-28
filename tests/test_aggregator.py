"""Tests for market aggregator - Kalshi/Jupiter parsing and MarketAlert."""

import pytest
from unittest.mock import patch, MagicMock

from src.market.aggregator import MarketAggregator, MarketAlert


@pytest.fixture
def aggregator():
    """Fixture for MarketAggregator."""
    return MarketAggregator()


def test_market_alert_dataclass():
    """Test MarketAlert structure."""
    alert = MarketAlert(
        source="kalshi",
        category="crypto",
        question="Will BTC hit $100k?",
        price=0.65,
        volume=50000.0,
        created_at="2025-01-01",
        url="https://kalshi.com/markets/BTC100K",
    )
    assert alert.source == "kalshi"
    assert alert.category == "crypto"
    assert alert.question == "Will BTC hit $100k?"
    assert alert.price == 0.65
    assert alert.volume == 50000.0
    assert alert.url == "https://kalshi.com/markets/BTC100K"


def test_get_kalshi_markets_parsing(aggregator):
    """Test Kalshi market parsing from API response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "markets": [
            {
                "title": "Will Bitcoin hit $100k by end of 2025?",
                "ticker": "BTC100K",
                "last_price": 0.65,
                "volume": 50000,
                "volume_num": 50000,
                "created_time": "2025-01-01T00:00:00",
            }
        ]
    }

    with patch.object(aggregator.session, "get", return_value=mock_resp):
        alerts = aggregator.get_kalshi_markets(limit=10)

    assert len(alerts) >= 1
    a = alerts[0]
    assert isinstance(a, MarketAlert)
    assert a.source == "kalshi"
    assert "Bitcoin" in a.question or "100k" in a.question
    assert a.price == 0.65
    assert a.volume == 50000.0
    assert "kalshi.com" in a.url


def test_get_jupiter_markets_parsing(aggregator):
    """Test Jupiter market parsing from API response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "metadata": {"title": "Crypto Event"},
                "markets": [
                    {
                        "marketId": "abc123",
                        "status": "open",
                        "metadata": {"title": "Will ETH hit $5k?"},
                        "pricing": {
                            "buyYesPriceUsd": 55000,
                            "volume": 10000,
                        },
                    }
                ],
            }
        ]
    }

    with patch.object(aggregator.session, "get", return_value=mock_resp):
        alerts = aggregator.get_jupiter_markets(category="crypto")

    assert len(alerts) >= 1
    a = alerts[0]
    assert isinstance(a, MarketAlert)
    assert a.source == "jupiter"
    assert a.category == "crypto"
    assert a.price == pytest.approx(0.55, rel=0.01)
    assert a.volume == 10000.0
    assert "jup.ag" in a.url


def test_get_kalshi_empty_response(aggregator):
    """Test Kalshi with empty markets."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"markets": []}

    with patch.object(aggregator.session, "get", return_value=mock_resp):
        alerts = aggregator.get_kalshi_markets(limit=10)

    assert alerts == []
