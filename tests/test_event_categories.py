"""Tests for EventAlerter category precision and keyword disambiguation."""

from unittest.mock import MagicMock

from src.alerts.events import EventAlerter


def _alerter() -> EventAlerter:
    api_factory = MagicMock()
    api_factory.get_polymarket_api.return_value = MagicMock()
    return EventAlerter(api_factory)


def test_is_crypto_short_term_requires_asset_timeframe_and_direction():
    alerter = _alerter()

    assert alerter.is_crypto_short_term("Will Bitcoin be higher in 15 minutes?")
    assert alerter.is_crypto_short_term("Will SOL go down in 5m?")
    assert not alerter.is_crypto_short_term("Will Lakers win in 15 minutes?")
    assert not alerter.is_crypto_short_term("Will Bitcoin hit 100k this year?")


def test_get_category_disambiguates_sports_vs_crypto_terms():
    alerter = _alerter()

    assert alerter.get_category("Will Orlando Magic win tonight?") == "sports"
    assert alerter.get_category("Will the Jacksonville Jaguars make playoffs?") == "sports"
    assert alerter.get_category("Will AVAX (Avalanche) rally 10% this week?") == "crypto"


def test_get_category_ambiguous_crypto_tokens_need_context():
    alerter = _alerter()

    # "LINK" should only classify as crypto when clearly chainlink-related.
    assert alerter.get_category("Will Chainlink (LINK) break $30 this month?") == "crypto"
    assert alerter.get_category("Will this link to policy doc be published?") == "other"

    # "TON" should only classify as crypto when clearly toncoin/open-network context.
    assert alerter.get_category("Will Toncoin (TON) outperform BTC this week?") == "crypto"
    assert alerter.get_category("Will a ton of rain hit NYC this weekend?") == "weather"


def test_filter_by_category_uses_precise_classification():
    alerter = _alerter()
    markets = [
        {"question": "Will Bitcoin be higher in 15 minutes?"},
        {"question": "Will Orlando Magic win tonight?"},
        {"question": "Will Congress pass the bill this week?"},
    ]

    crypto = alerter.filter_by_category(markets, ["crypto"])
    sports = alerter.filter_by_category(markets, ["sports"])
    politics = alerter.filter_by_category(markets, ["politics"])

    assert len(crypto) == 1
    assert len(sports) == 1
    assert len(politics) == 1
