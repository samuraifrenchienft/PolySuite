"""Tests for wallet vetting streak/reliability metrics."""

from unittest.mock import MagicMock

from src.wallet.vetting import WalletVetting


def _mock_api_factory(trades, markets):
    api = MagicMock()
    api.get_wallet_trades.return_value = trades
    api.get_market.side_effect = lambda mid: markets.get(mid)
    api.get_closed_positions.return_value = []
    api.get_wallet_positions.return_value = []
    factory = MagicMock()
    factory.get_polymarket_api.return_value = api
    factory.get_jupiter_prediction_client.return_value = api
    return factory


def test_vetting_computes_streak_recent_and_reliability():
    trades = [
        {"conditionId": "m1", "size": 100, "price": 0.4, "side": "BUY", "outcome": "yes", "createdAt": "2026-01-01T00:00:00Z"},
        {"conditionId": "m2", "size": 100, "price": 0.6, "side": "SELL", "outcome": "yes", "createdAt": "2026-01-02T00:00:00Z"},
        {"conditionId": "m3", "size": 100, "price": 0.5, "side": "BUY", "outcome": "yes", "createdAt": "2026-01-03T00:00:00Z"},
        {"conditionId": "m4", "size": 100, "price": 0.5, "side": "BUY", "outcome": "yes", "createdAt": "2026-01-04T00:00:00Z"},
        {"conditionId": "m5", "size": 100, "price": 0.5, "side": "BUY", "outcome": "yes", "createdAt": "2026-01-05T00:00:00Z"},
        {"conditionId": "m6", "size": 100, "price": 0.5, "side": "BUY", "outcome": "yes", "createdAt": "2026-01-06T00:00:00Z"},
    ]
    markets = {
        "m1": {"resolved": True, "outcome": "yes", "category": "crypto", "question": "q1"},
        "m2": {"resolved": True, "outcome": "no", "category": "crypto", "question": "q2"},
        "m3": {"resolved": True, "outcome": "yes", "category": "crypto", "question": "q3"},
        "m4": {"resolved": True, "outcome": "no", "category": "sports", "question": "q4"},
        "m5": {"resolved": True, "outcome": "yes", "category": "sports", "question": "q5"},
        "m6": {"resolved": True, "outcome": "yes", "category": "sports", "question": "q6"},
    }
    vetter = WalletVetting(_mock_api_factory(trades, markets))
    result = vetter.vet_wallet("0xabc", min_bet=1)

    assert result is not None
    assert result["win_rate_real"] == 5 / 6 * 100
    assert result["current_win_streak"] == 2
    assert result["max_win_streak"] == 3
    assert result["recent_wins"] == 5
    assert result["recent_win_rate"] == 5 / 6 * 100
    assert 0 <= result["reliability_score"] <= 100

