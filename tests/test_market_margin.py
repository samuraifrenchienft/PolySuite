"""Tests for binary entry margin gating (alert_min_entry_roi_pct)."""

from src.alerts.market_margin import (
    assign_alert_priority,
    entry_meets_min_stake_roi,
    insider_winning_trade_passes_entry_roi,
    insider_winning_trade_stake_roi_pct,
    majority_convergence_side,
    max_implied_price_for_min_roi,
    normalize_yes_no,
    parse_outcome_prices,
    stake_roi_if_win_pct,
    convergence_passes_entry_roi,
)


def test_stake_roi_if_win_pct():
    assert abs(stake_roi_if_win_pct(0.5) - 100.0) < 1e-6
    assert abs(stake_roi_if_win_pct(0.9) - (0.1 / 0.9 * 100)) < 1e-6


def test_max_implied_price_for_min_roi():
    # 12% ROI if win => p <= 100/112
    p = max_implied_price_for_min_roi(12.0)
    assert p is not None and abs(p - 100.0 / 112.0) < 1e-6


def test_entry_meets_min_stake_roi():
    assert entry_meets_min_stake_roi(0.85, 12.0) is True  # ~17.6% ROI
    assert entry_meets_min_stake_roi(0.93, 12.0) is False  # thin margin
    assert entry_meets_min_stake_roi(None, 12.0) is True  # unknown: do not block


def test_parse_outcome_prices_string():
    m = {"outcomePrices": "[0.6, 0.4]"}
    assert parse_outcome_prices(m) == (0.6, 0.4)


def test_majority_convergence_side():
    wallets = [
        {"side": "Yes"},
        {"side": "NO"},
        {"side": "yes"},
    ]
    assert majority_convergence_side(wallets) == "YES"


def test_normalize_yes_no_mixed_labels():
    assert normalize_yes_no("BUY YES") == "YES"
    assert normalize_yes_no("outcome: no") == "NO"
    assert normalize_yes_no("BUY") is None


def test_assign_alert_priority_roi_only():
    cfg = {
        "alert_priority_enabled": True,
        "alert_priority_high_min_roi_pct": 25,
        "alert_priority_medium_min_roi_pct": 15,
        "alert_priority_insider_bump": False,
    }
    assert assign_alert_priority(stake_roi_pct=30.0, config=cfg) == "HIGH"
    assert assign_alert_priority(stake_roi_pct=18.0, config=cfg) == "MEDIUM"
    assert assign_alert_priority(stake_roi_pct=12.0, config=cfg) == "LOW"


def test_assign_alert_priority_disabled():
    cfg = {"alert_priority_enabled": False}
    assert assign_alert_priority(stake_roi_pct=99.0, config=cfg) == "MEDIUM"


def test_convergence_passes_entry_roi():
    conv = {
        "market_info": {"outcomePrices": [0.5, 0.5]},
        "wallets": [{"side": "YES"}, {"side": "YES"}],
    }
    assert convergence_passes_entry_roi(conv, 12.0) is True

    conv_tight = {
        "market_info": {"outcomePrices": [0.95, 0.05]},
        "wallets": [{"side": "YES"}, {"side": "YES"}],
    }
    assert convergence_passes_entry_roi(conv_tight, 12.0) is False


def test_convergence_fail_closed_when_side_ambiguous_but_prices_present():
    conv_ambiguous = {
        "market_info": {"outcomePrices": [0.95, 0.05]},
        "wallets": [{"side": "BUY"}, {"side": "SELL"}],
    }
    assert convergence_passes_entry_roi(conv_ambiguous, 12.0) is False


def test_convergence_allow_when_side_ambiguous_and_no_prices():
    conv_unknown = {
        "market_info": {},
        "wallets": [{"side": "BUY"}, {"side": "SELL"}],
    }
    assert convergence_passes_entry_roi(conv_unknown, 12.0) is True


class _FakePoly:
    def __init__(self, market):
        self.market = market
        self.calls = 0

    def get_market(self, _market_id):
        self.calls += 1
        return self.market


def test_insider_market_fetch_reused_by_cache():
    signal = {
        "winning_trade": {
            "market_id": "m1",
            "side": "YES",
        }
    }
    poly = _FakePoly({"outcomePrices": [0.6, 0.4]})
    cache = {}

    assert insider_winning_trade_passes_entry_roi(signal, poly, 12.0, market_cache=cache)
    assert insider_winning_trade_stake_roi_pct(signal, poly, market_cache=cache) is not None
    assert poly.calls == 1
