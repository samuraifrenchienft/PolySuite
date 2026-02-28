"""Tests for RTDS client trade parsing (activity:trades payload)."""

import pytest
from src.market.rtds_client import RTDSClient


class TestRTDSParseTrade:
    """Test RTDSClient._parse_trade extracts proxyWallet, market, asset_id, size, price, side."""

    def test_standard_payload_extracts_all_fields(self):
        """Standard activity:trades payload with canonical field names."""
        client = RTDSClient()
        payload = {
            "proxyWallet": "0xabc123",
            "market": "0xmarket456",
            "asset_id": "0xasset789",
            "size": 100.5,
            "price": 0.65,
            "side": "BUY",
        }
        trade = client._parse_trade(payload)
        assert trade is not None
        assert trade["proxyWallet"] == "0xabc123"
        assert trade["market"] == "0xmarket456"
        assert trade["asset_id"] == "0xasset789"
        assert trade["size"] == 100.5
        assert trade["price"] == 0.65
        assert trade["side"] == "BUY"
        assert "raw" in trade

    def test_alternate_field_names(self):
        """Alternate Polymarket payload shapes: proxy_wallet, conditionId, assetId, amount, outcomePrice."""
        client = RTDSClient()
        payload = {
            "proxy_wallet": "0xdef456",
            "conditionId": "0xcond123",
            "assetId": "0xtoken456",
            "amount": 50.0,
            "outcomePrice": 0.35,
            "outcome": "SELL",
        }
        trade = client._parse_trade(payload)
        assert trade is not None
        assert trade["proxyWallet"] == "0xdef456"
        assert trade["market"] == "0xcond123"
        assert trade["asset_id"] == "0xtoken456"
        assert trade["size"] == 50.0
        assert trade["price"] == 0.35
        assert trade["side"] == "SELL"

    def test_maker_taker_fallback_for_proxy_wallet(self):
        """When proxyWallet missing, use maker or taker."""
        client = RTDSClient()
        payload = {"maker": "0xmaker123", "market": "m1", "size": 10, "price": 0.5}
        trade = client._parse_trade(payload)
        assert trade is not None
        assert trade["proxyWallet"] == "0xmaker123"

        payload2 = {"taker": "0xtaker456", "conditionId": "c1", "size": 20, "price": 0.6}
        trade2 = client._parse_trade(payload2)
        assert trade2 is not None
        assert trade2["proxyWallet"] == "0xtaker456"

    def test_empty_payload_returns_none(self):
        """Empty payload returns None."""
        client = RTDSClient()
        assert client._parse_trade({}) is None
        assert client._parse_trade(None) is None

    def test_missing_proxy_wallet_returns_none(self):
        """Payload without any wallet identifier returns None."""
        client = RTDSClient()
        payload = {"market": "m1", "asset_id": "a1", "size": 10, "price": 0.5}
        assert client._parse_trade(payload) is None

    def test_defaults_for_missing_optional_fields(self):
        """Missing size/price/side use defaults."""
        client = RTDSClient()
        payload = {"proxyWallet": "0xaddr", "market": "m1"}
        trade = client._parse_trade(payload)
        assert trade is not None
        assert trade["size"] == 0.0
        assert trade["price"] == 0.0
        assert trade["side"] == "BUY"
