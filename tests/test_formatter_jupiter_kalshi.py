"""Tests for Jupiter/Kalshi formatters."""

import pytest
from src.market.aggregator import MarketAlert
from src.alerts.formatter import formatter


def test_format_kalshi_market_dataclass():
    """Test format_kalshi_market with MarketAlert dataclass."""
    alert = MarketAlert(
        source="kalshi",
        category="crypto",
        question="Will Bitcoin hit $100k by end of 2025?",
        price=0.65,
        volume=50000.0,
        created_at="",
        url="https://kalshi.com/markets/BTC100K",
    )
    msg = formatter.format_kalshi_market(alert)
    assert "KALSHI" in msg
    assert "Bitcoin" in msg or "100k" in msg
    assert "50,000" in msg or "50000" in msg
    assert "65" in msg
    assert "kalshi.com" in msg


def test_format_kalshi_market_dict():
    """Test format_kalshi_market with dict."""
    alert = {
        "question": "Will ETH hit $5k?",
        "price": 0.55,
        "volume": 25000,
        "url": "https://kalshi.com/markets/ETH5K",
    }
    msg = formatter.format_kalshi_market(alert)
    assert "KALSHI" in msg
    assert "ETH" in msg or "5k" in msg
    assert "55" in msg


def test_format_jupiter_market_dataclass():
    """Test format_jupiter_market with MarketAlert dataclass."""
    alert = MarketAlert(
        source="jupiter",
        category="crypto",
        question="Will SOL hit $200?",
        price=0.72,
        volume=15000.0,
        created_at="",
        url="https://jup.ag/prediction/sol200",
    )
    msg = formatter.format_jupiter_market(alert)
    assert "JUPITER" in msg
    assert "SOL" in msg or "200" in msg
    assert "15,000" in msg or "15000" in msg
    assert "72" in msg
    assert "jup.ag" in msg


def test_format_jupiter_market_dict():
    """Test format_jupiter_market with dict."""
    alert = {
        "question": "Crypto: Will BTC hit $100k?",
        "price": 0.5,
        "volume": 1000,
        "url": "https://jup.ag/prediction/btc",
    }
    msg = formatter.format_jupiter_market(alert)
    assert "JUPITER" in msg
    assert "50" in msg or "0.5" in msg
