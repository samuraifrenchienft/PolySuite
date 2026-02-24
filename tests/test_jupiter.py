"""Tests for the Jupiter client."""

import pytest
from unittest.mock import patch, MagicMock
from src.market.jupiter import JupiterClient

@pytest.fixture
def client():
    """Fixture for the JupiterClient."""
    return JupiterClient()

def test_get_quote_success(client):
    """Test get_quote successfully."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "test_quote"}

    with patch('requests.get', return_value=mock_response) as mock_get:
        quote = client.get_quote("input_mint", "output_mint", 100)
        assert quote == {"data": "test_quote"}
        mock_get.assert_called_once_with(
            f"{client.api_url}/swap/v1/quote",
            params={
                "inputMint": "input_mint",
                "outputMint": "output_mint",
                "amount": 100,
                "slippageBps": 50,
            },
            headers=client.headers,
            timeout=30,
        )

import requests

def test_get_quote_error(client):
    """Test get_quote with an API error."""
    with patch('requests.get', side_effect=requests.exceptions.RequestException("API Error")) as mock_get:
        quote = client.get_quote("input_mint", "output_mint", 100)
        assert quote is None

def test_get_swap_instructions_success(client):
    """Test get_swap_instructions successfully."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "test_swap"}

    with patch('requests.post', return_value=mock_response) as mock_post:
        swap_instructions = client.get_swap_instructions({}, "user_public_key")
        assert swap_instructions == {"data": "test_swap"}
        mock_post.assert_called_once_with(
            f"{client.api_url}/swap",
            json={
                "quoteResponse": {},
                "userPublicKey": "user_public_key",
                "wrapAndUnwrapSol": True,
            },
            headers=client.headers,
            timeout=30,
        )

def test_get_swap_instructions_error(client):
    """Test get_swap_instructions with an API error."""
    with patch('requests.post', side_effect=requests.exceptions.RequestException("API Error")) as mock_post:
        swap_instructions = client.get_swap_instructions({}, "user_public_key")
        assert swap_instructions is None
