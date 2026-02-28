"""Tests for BankrClient. Skips live API tests when BANKR_API_KEY unset."""

import os
from unittest.mock import patch

import pytest

from src.market.bankr import BankrClient


class TestBankrClientConfig:
    """Test BankrClient configuration."""

    def test_is_configured_false_when_empty(self):
        """is_configured returns False when no API key."""
        client = BankrClient()
        assert client.is_configured() is False

    def test_is_configured_true_when_key_set(self):
        """is_configured returns True when API key provided."""
        client = BankrClient(api_key="test-key-123")
        assert client.is_configured() is True

    def test_user_api_key_takes_priority(self):
        """user_api_key overrides api_key."""
        client = BankrClient(api_key="default", user_api_key="user-key")
        assert client.api_key == "user-key"


class TestBankrClientSendPrompt:
    """Test send_prompt with mocked HTTP."""

    def test_send_prompt_unconfigured_returns_none(self):
        """When not configured, send_prompt returns (None, error_msg)."""
        client = BankrClient()
        job_id, err = client.send_prompt("test prompt")
        assert job_id is None
        assert "not configured" in (err or "").lower() or "BANKR" in (err or "")

    @patch("src.market.bankr.requests.post")
    def test_send_prompt_success_returns_job_id(self, mock_post):
        """When API returns 200/202, returns jobId."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"jobId": "job-abc123"}
        client = BankrClient(api_key="test-key")
        job_id, err = client.send_prompt("bet $10 on yes")
        assert job_id == "job-abc123"
        assert err is None

    @patch("src.market.bankr.requests.post")
    def test_send_prompt_401_returns_error(self, mock_post):
        """401 returns None and error message."""
        mock_post.return_value.status_code = 401
        mock_post.return_value.json.return_value = {"message": "Invalid API key"}
        client = BankrClient(api_key="bad-key")
        job_id, err = client.send_prompt("test")
        assert job_id is None
        assert err is not None


@pytest.mark.skipif(
    not os.environ.get("BANKR_API_KEY"),
    reason="BANKR_API_KEY not set; skip live Bankr API test",
)
class TestBankrClientLive:
    """Live API tests - run only when BANKR_API_KEY is set."""

    def test_send_prompt_live(self):
        """Send real prompt to Bankr API (slow, requires key)."""
        client = BankrClient(api_key=os.environ["BANKR_API_KEY"])
        job_id, err = client.send_prompt("What is 2+2?")
        assert err is None or "limit" in (err or "").lower()
        # May get job_id or rate limit error
        if job_id:
            assert isinstance(job_id, str)
