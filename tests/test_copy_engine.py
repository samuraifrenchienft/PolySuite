"""Tests for CopyEngine qualify logic (odds, size, throttle, freeze)."""

import time
from src.copy.engine import CopyEngine


class TestCopyEngineQualify:
    """Test CopyEngine._qualify: odds range, size cap, pause, throttle, freeze."""

    def _valid_trade(self):
        return {"proxyWallet": "0xabc", "market": "m1", "asset_id": "a1", "size": 100, "price": 0.5, "side": "BUY"}

    def test_valid_trade_passes_with_default_config(self):
        """Trade within odds and size limits passes."""
        engine = CopyEngine(config={})
        trade = self._valid_trade()
        assert engine._qualify(trade) is True

    def test_copy_pause_blocks_all(self):
        """copy_pause=True blocks regardless of trade."""
        engine = CopyEngine(config={"copy_pause": True})
        trade = self._valid_trade()
        assert engine._qualify(trade) is False

    def test_price_below_min_odds_rejected(self):
        """Price below copy_min_odds rejected."""
        engine = CopyEngine(config={"copy_min_odds": 0.2, "copy_max_odds": 0.95, "copy_max_order_usd": 100})
        trade = self._valid_trade()
        trade["price"] = 0.1
        trade["size"] = 50
        assert engine._qualify(trade) is False

    def test_price_above_max_odds_rejected(self):
        """Price above copy_max_odds rejected."""
        engine = CopyEngine(config={"copy_min_odds": 0.05, "copy_max_odds": 0.8, "copy_max_order_usd": 100})
        trade = self._valid_trade()
        trade["price"] = 0.9
        trade["size"] = 50
        assert engine._qualify(trade) is False

    def test_order_usd_exceeds_max_rejected(self):
        """order_usd (size * price) > copy_max_order_usd rejected."""
        engine = CopyEngine(config={"copy_min_odds": 0.05, "copy_max_odds": 0.95, "copy_max_order_usd": 50})
        trade = self._valid_trade()
        trade["price"] = 0.5
        trade["size"] = 200  # 200 * 0.5 = 100 > 50
        assert engine._qualify(trade) is False

    def test_order_usd_zero_or_negative_rejected(self):
        """Zero or negative order_usd rejected."""
        engine = CopyEngine(config={"copy_min_odds": 0.05, "copy_max_odds": 0.95, "copy_max_order_usd": 100})
        trade = self._valid_trade()
        trade["size"] = 0
        assert engine._qualify(trade) is False

        trade["size"] = 100
        trade["price"] = 0
        assert engine._qualify(trade) is False

    def test_valid_trade_at_boundaries_passes(self):
        """Trade at min/max odds and size boundary passes."""
        engine = CopyEngine(config={"copy_min_odds": 0.1, "copy_max_odds": 0.9, "copy_max_order_usd": 90})
        trade = self._valid_trade()
        trade["price"] = 0.1
        trade["size"] = 100  # 10 USD
        assert engine._qualify(trade) is True

        trade["price"] = 0.9
        trade["size"] = 100  # 90 USD
        assert engine._qualify(trade) is True

    def test_throttle_blocks_when_over_limit(self):
        """When over copy_max_trades_per_minute, _qualify returns False."""
        engine = CopyEngine(config={"copy_max_trades_per_minute": 2})
        # Fill the throttle window with 2 recent timestamps (within last 60s)
        now = time.time()
        engine._trade_timestamps.append(now - 10)
        engine._trade_timestamps.append(now - 5)
        trade = self._valid_trade()
        assert engine._qualify(trade) is False

    def test_freeze_blocks_when_in_freeze_window(self):
        """When _freeze_until > now, _qualify returns False."""
        engine = CopyEngine(config={})
        engine._freeze_until = 9999999999.0  # far future
        trade = self._valid_trade()
        assert engine._qualify(trade) is False
