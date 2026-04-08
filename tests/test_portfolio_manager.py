import pytest
from ib_async import IB, Ticker

from thetagang.portfolio_manager import PortfolioManager


@pytest.fixture
def mock_ib(mocker):
    mock = mocker.Mock(spec=IB)
    mock.orderStatusEvent = mocker.Mock()
    mock.orderStatusEvent.__iadd__ = mocker.Mock(return_value=None)
    return mock


@pytest.fixture
def mock_config(mocker):
    config = mocker.Mock()
    config.runtime.account.number = "TEST123"
    config.runtime.account.margin_usage = 0.5
    config.runtime.account.market_data_type = 1
    config.runtime.account.cancel_orders = False
    config.runtime.ib_async.api_response_wait_time = 1
    config.runtime.orders.exchange = "SMART"
    config.runtime.orders.price_update_delay = [30, 60]
    config.strategies.grid.symbols = {
        "SPY": mocker.Mock(primary_exchange="ARCA")
    }
    return config


@pytest.fixture
def portfolio_manager(mock_ib, mock_config, mocker):
    completion_future = mocker.Mock()
    return PortfolioManager(mock_config, mock_ib, completion_future, dry_run=False)


class TestPortfolioManager:
    def test_get_close_price_with_valid_close(self, mocker):
        ticker = mocker.Mock(spec=Ticker)
        ticker.close = 100.50
        ticker.marketPrice.return_value = 101.00
        mocker.patch("ib_async.util.isNan", return_value=False)

        result = PortfolioManager.get_close_price(ticker)
        assert result == 100.50

    def test_get_close_price_with_nan_close(self, mocker):
        ticker = mocker.Mock(spec=Ticker)
        ticker.close = float("nan")
        ticker.marketPrice.return_value = 101.00
        mocker.patch("ib_async.util.isNan", return_value=True)

        result = PortfolioManager.get_close_price(ticker)
        assert result == 101.00

    def test_stage_enabled_true_for_grid(self, portfolio_manager):
        assert portfolio_manager.stage_enabled("equity_grid_spread") is True

    def test_stage_enabled_false_for_unknown(self, portfolio_manager):
        assert portfolio_manager.stage_enabled("options_write_puts") is False

    def test_get_symbols_returns_grid_symbols(self, portfolio_manager):
        assert portfolio_manager.get_symbols() == ["SPY"]

    def test_get_buying_power(self, portfolio_manager, mocker):
        account_summary = {
            "NetLiquidation": mocker.Mock(value="100000")
        }
        bp = portfolio_manager.get_buying_power(account_summary)
        assert bp == 50000  # 100000 * 0.5

    def test_grid_strategy_deps_contains_engine(self, portfolio_manager):
        from thetagang.strategies.grid_spread_engine import GridCreditSpreadEngine
        deps = portfolio_manager._grid_strategy_deps({"equity_grid_spread"})
        assert isinstance(deps.service, GridCreditSpreadEngine)
        assert "equity_grid_spread" in deps.enabled_stages
