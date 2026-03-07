from datetime import datetime, timedelta

from backtest.storage import BacktestStorage


class _FakeAPI:
    def __init__(self, winners):
        self._winners = winners

    def get_market_details(self, market_id: str):
        winner = self._winners.get(market_id)
        if winner is None:
            return {"id": market_id, "resolved": False, "winner": None}
        return {"id": market_id, "resolved": True, "winner": winner}


def test_log_suggestion_dedupes_and_resolves(tmp_path):
    db_path = str(tmp_path / "polysuite.db")
    storage = BacktestStorage(db_path=db_path)

    # First write succeeds
    assert storage.log_suggestion(
        source="crypto",
        category="crypto_short_term",
        market_id="m1",
        question="Will BTC close higher?",
        side="YES",
        entry_price=0.55,
    )
    # Duplicate market+side within dedupe window should be skipped
    assert not storage.log_suggestion(
        source="crypto",
        category="crypto_short_term",
        market_id="m1",
        question="Will BTC close higher?",
        side="YES",
        entry_price=0.56,
    )
    # Opposite side is allowed
    assert storage.log_suggestion(
        source="crypto",
        category="crypto_short_term",
        market_id="m1",
        question="Will BTC close higher?",
        side="NO",
        entry_price=0.45,
    )

    api = _FakeAPI({"m1": "yes"})
    result = storage.resolve_open_suggestions(api, stake_usd=100.0, max_per_run=20)
    assert result["resolved"] == 2
    assert result["wins"] == 1
    assert result["losses"] == 1


def test_suggestion_summary_counts_and_pnl(tmp_path):
    db_path = str(tmp_path / "polysuite.db")
    storage = BacktestStorage(db_path=db_path)

    storage.log_suggestion(
        source="sports",
        category="sports",
        market_id="s1",
        question="Team A wins?",
        side="YES",
        entry_price=0.61,
        dedupe_window_seconds=0,
    )
    storage.log_suggestion(
        source="politics",
        category="politics",
        market_id="p1",
        question="Candidate wins?",
        side="NO",
        entry_price=0.42,
        dedupe_window_seconds=0,
    )

    # Resolve only one market
    api = _FakeAPI({"s1": "yes"})
    storage.resolve_open_suggestions(api, stake_usd=50.0, max_per_run=20)

    since_ts = (datetime.utcnow() - timedelta(days=1)).isoformat()
    summary = storage.get_suggestion_summary(since_ts)
    assert summary["total"] == 2
    assert summary["resolved"] == 1
    assert summary["open"] == 1
    assert summary["wins"] == 1
    assert summary["losses"] == 0
    assert summary["pnl_usd"] == 50.0
