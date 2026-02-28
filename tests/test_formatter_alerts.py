"""Tests for convergence, curated wallet (whale batch), contrarian, and insider formatters."""

from src.alerts.formatter import formatter


class TestFormatConvergence:
    """Test format_convergence output."""

    def test_basic_convergence_alert(self):
        """Convergence alert with market, wallets, urgency."""
        market = {"question": "Will BTC hit $100k?", "conditionId": "0x123"}
        wallets = [
            {"nickname": "Alpha", "win_rate": 72, "side": "YES", "entry_price": 0.45, "size": 500},
            {"nickname": "Beta", "win_rate": 68, "side": "YES", "entry_price": 0.48, "size": 300},
        ]
        convergence = {"has_early_entry": True}
        msg = formatter.format_convergence(market, wallets, convergence)
        assert "CONVERGENCE" in msg
        assert "BTC" in msg or "100k" in msg
        assert "2 traders" in msg
        assert "Early: Yes" in msg
        assert "Alpha" in msg
        assert "Beta" in msg

    def test_convergence_with_recommendation(self):
        """Convergence with entry_zone and conviction."""
        market = {"question": "Test market?"}
        wallets = [{"nickname": "W1", "win_rate": 70}]
        convergence = {"has_early_entry": False}
        msg = formatter.format_convergence(
            market, wallets, convergence, entry_zone="BUY", conviction="HIGH", entry_reason="Strong signal"
        )
        assert "RECOMMENDATION" in msg
        assert "BUY" in msg
        assert "Strong signal" in msg


class TestFormatWhaleBatch:
    """Test format_whale_batch (curated wallet activity)."""

    def test_empty_trades_returns_empty(self):
        """Empty trades returns empty string."""
        assert formatter.format_whale_batch([]) == ""

    def test_curated_wallet_activity_format(self):
        """Whale batch formats trades by wallet; user-facing text says CURATED WALLET not whale."""
        trades = [
            {"wallet": "0xabc...", "question": "Will ETH hit $5k?", "side": "YES", "size": 1000, "entry_price": 0.55},
            {"wallet": "0xabc...", "question": "Will SOL hit $200?", "side": "NO", "size": 500, "entry_price": 0.4},
        ]
        msg = formatter.format_whale_batch(trades)
        assert "CURATED WALLET" in msg
        assert "2 trades" in msg
        assert "1 wallets" in msg
        assert "ETH" in msg or "5k" in msg


class TestFormatContrarian:
    """Test format_contrarian output."""

    def test_basic_contrarian_alert(self):
        """Contrarian alert with volume, majority/minority, payout."""
        signal = {
            "question": "Will BTC hit $100k by EOY?",
            "vol_yes": 50000,
            "vol_no": 10000,
            "majority_side": "YES",
            "minority_side": "NO",
            "minority_price": 0.25,
            "payout": 4.0,
            "total_volume": 60000,
            "score": 12.5,
            "market_id": "0x123",
        }
        msg = formatter.format_contrarian(signal)
        assert "CONTRARIAN" in msg
        assert "BTC" in msg or "100k" in msg
        assert "50,000" in msg or "50000" in msg
        assert "Crowd on YES" in msg
        assert "bet NO" in msg
        assert "0.25" in msg
        assert "4.0" in msg


class TestFormatInsiderSignal:
    """Test format_insider_signal output."""

    def test_basic_insider_signal(self):
        """Insider signal with address, trade size, winning trade."""
        signal = {
            "address": "0x1234567890abcdef1234567890abcdef12345678",
            "trade_size": 5000,
            "closed_count": 3,
            "risk": "HIGH",
            "winning_trade": {"question": "Will ETH hit $5k?", "pnl": 250.50},
        }
        msg = formatter.format_insider_signal(signal)
        assert "INSIDER" in msg
        assert "5,000" in msg or "5000" in msg
        assert "3 trades" in msg
        assert "ETH" in msg or "5k" in msg
        assert "250" in msg
