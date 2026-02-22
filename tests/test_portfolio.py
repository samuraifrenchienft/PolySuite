
import pytest
from unittest.mock import MagicMock, patch
from src.wallet.portfolio import Portfolio, Position
from src.wallet.portfolio_calculator import PortfolioCalculator
from src.market.api import APIClientFactory

@pytest.fixture
def mock_api_factory():
    """Fixture for a mocked APIClientFactory."""
    factory = MagicMock(spec=APIClientFactory)
    factory.get_polymarket_api.return_value = MagicMock()
    return factory

def test_calculate_portfolio_success(mock_api_factory):
    """Test successful portfolio calculation."""
    # Arrange
    mock_api = mock_api_factory.get_polymarket_api()
    mock_api.get_wallet_positions.return_value = [
        {"market_id": "1", "outcome": "Yes", "shares": 10, "entry_price": 0.5, "token_id": "1"}
    ]
    mock_api.get_market.return_value = {"question": "Test Market?"}
    mock_api.get_token_price.return_value = 0.6

    calculator = PortfolioCalculator(mock_api_factory)

    # Act
    portfolio = calculator.calculate_portfolio("0x123", "Test Wallet")

    # Assert
    assert isinstance(portfolio, Portfolio)
    assert portfolio.address == "0x123"
    assert portfolio.nickname == "Test Wallet"
    assert portfolio.total_value == 6.0
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].market == "Test Market?"
    assert portfolio.positions[0].value == 6.0

def test_calculate_portfolio_no_positions(mock_api_factory):
    """Test portfolio calculation with no positions."""
    # Arrange
    mock_api = mock_api_factory.get_polymarket_api()
    mock_api.get_wallet_positions.return_value = []

    calculator = PortfolioCalculator(mock_api_factory)

    # Act
    portfolio = calculator.calculate_portfolio("0x123", "Test Wallet")

    # Assert
    assert isinstance(portfolio, Portfolio)
    assert portfolio.total_value == 0
    assert len(portfolio.positions) == 0
