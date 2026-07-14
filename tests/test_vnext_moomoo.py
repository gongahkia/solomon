from __future__ import annotations

import inspect
import socket
import threading
from importlib import metadata

import pytest

from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError
from stonks_cli.vnext.moomoo import (
    LocalOpenDReadOnlyClient,
    MoomooAccount,
    MoomooAccountBalance,
    MoomooCashFlow,
    MoomooHistoricalCandle,
    MoomooHistoricalOrder,
    MoomooInstrument,
    MoomooMarketDataEntitlements,
    MoomooMarketDataSubscription,
    MoomooOpenDProcessContract,
    MoomooOpenOrder,
    MoomooOrderHistoryWindow,
    MoomooPosition,
    MoomooReadOnlyAccountClient,
    MoomooReadOnlyBalanceClient,
    MoomooReadOnlyCashFlowClient,
    MoomooReadOnlyHistoricalCandleClient,
    MoomooReadOnlyMarketDataEntitlementClient,
    MoomooReadOnlyOpenOrderClient,
    MoomooReadOnlyOrderHistoryClient,
    MoomooReadOnlyPositionClient,
    MoomooReadOnlySGQuoteClient,
    MoomooReadOnlyUSQuoteClient,
    MoomooSdkStatus,
    MoomooSGQuote,
    MoomooTradeUnlockState,
    MoomooUSQuote,
    OpenDEndpointStatus,
    check_moomoo_sdk_compatibility,
    normalize_moomoo_instruments,
    probe_local_opend,
    read_moomoo_trade_unlock_state_without_secrets,
    resolve_moomoo_us_equity_symbol,
    select_moomoo_account,
)


def test_moomoo_opend_process_contract_is_operator_managed_and_read_only():
    contract = MoomooOpenDProcessContract("LOCALHOST", 11111)

    assert contract.to_data() == {
        "host": "localhost",
        "port": 11111,
        "operator_starts_gateway": True,
        "operator_logs_in_gateway": True,
        "cli_may_start_gateway": False,
        "cli_may_unlock_trading": False,
        "cli_may_submit_orders": False,
    }


@pytest.mark.parametrize("kwargs", [{"host": "192.0.2.1"}, {"host": "127.0.0.1", "port": 0}, {"host": "127.0.0.1", "operator_logs_in_gateway": False}])
def test_moomoo_opend_process_contract_rejects_malformed_or_unmanaged_processes(kwargs):
    values = {"host": "127.0.0.1", "port": 11111}
    values.update(kwargs)

    with pytest.raises(ValueError):
        MoomooOpenDProcessContract(**values)


@pytest.mark.parametrize("flag", ["cli_may_start_gateway", "cli_may_unlock_trading", "cli_may_submit_orders"])
def test_moomoo_opend_process_contract_denies_execution_actions(flag):
    with pytest.raises(VNextExecutionDeniedError):
        MoomooOpenDProcessContract("127.0.0.1", 11111, **{flag: True})


def test_local_opend_probe_reports_tcp_availability_without_broker_commands():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        _, port = listener.getsockname()

        result = probe_local_opend(MoomooOpenDProcessContract("127.0.0.1", port))

    assert result.status is OpenDEndpointStatus.AVAILABLE
    assert result.code == "available"
    assert result.latency_ms is not None


def test_local_opend_probe_fails_closed_when_endpoint_is_unavailable():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        _, port = listener.getsockname()

    result = probe_local_opend(MoomooOpenDProcessContract("127.0.0.1", port), timeout_seconds=0.1)

    assert result.status is OpenDEndpointStatus.UNAVAILABLE
    assert result.code == "connection_unavailable"
    assert result.latency_ms is None


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), "1"])
def test_local_opend_probe_rejects_malformed_timeout(timeout_seconds):
    with pytest.raises(ValueError):
        probe_local_opend(MoomooOpenDProcessContract("127.0.0.1", 11111), timeout_seconds=timeout_seconds)


def test_local_opend_socket_client_only_receives_data():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        _, port = listener.getsockname()

        def send_fixture() -> None:
            connection, _ = listener.accept()
            with connection:
                connection.sendall(b"fixture-response")

        thread = threading.Thread(target=send_fixture)
        thread.start()
        client = LocalOpenDReadOnlyClient(MoomooOpenDProcessContract("127.0.0.1", port))
        with client.connect() as connection:
            assert connection.receive() == b"fixture-response"
            assert not hasattr(connection, "send")
        thread.join(timeout=1)
        assert not thread.is_alive()


def test_local_opend_socket_client_fails_closed_when_unavailable():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        _, port = listener.getsockname()

    with pytest.raises(VNextExternalDataError):
        LocalOpenDReadOnlyClient(MoomooOpenDProcessContract("127.0.0.1", port), timeout_seconds=0.1).connect()


def test_moomoo_sdk_compatibility_checks_official_distribution_and_module_without_importing_sdk():
    result = check_moomoo_sdk_compatibility(distribution_version=lambda name: "9.1.0", module_finder=lambda name: object())

    assert result.status is MoomooSdkStatus.COMPATIBLE
    assert result.code == "sdk_compatible"
    assert result.version == "9.1.0"


def test_moomoo_sdk_compatibility_fails_closed_for_missing_or_malformed_sdk():
    missing = check_moomoo_sdk_compatibility(
        distribution_version=lambda name: (_ for _ in ()).throw(metadata.PackageNotFoundError()),
        module_finder=lambda name: object(),
    )
    malformed = check_moomoo_sdk_compatibility(distribution_version=lambda name: "", module_finder=lambda name: object())
    absent_module = check_moomoo_sdk_compatibility(distribution_version=lambda name: "9.1.0", module_finder=lambda name: None)

    assert (missing.status, missing.code, missing.version) == (MoomooSdkStatus.NOT_INSTALLED, "sdk_not_installed", None)
    assert (malformed.status, malformed.code, malformed.version) == (MoomooSdkStatus.INCOMPATIBLE, "sdk_invalid_version", None)
    assert (absent_module.status, absent_module.code, absent_module.version) == (MoomooSdkStatus.INCOMPATIBLE, "sdk_module_unavailable", None)


def test_moomoo_trade_unlock_state_is_explicitly_unknown_without_secret_or_mutation():
    evidence = read_moomoo_trade_unlock_state_without_secrets()

    assert evidence.state is MoomooTradeUnlockState.UNKNOWN
    assert evidence.code == "state_not_observable_without_secret_or_mutation"
    assert evidence.secret_used is False
    assert evidence.state_mutated is False
    assert inspect.signature(read_moomoo_trade_unlock_state_without_secrets).parameters == {}


def test_moomoo_read_only_account_client_reads_sorts_and_closes_context():
    class Context:
        closed = False

        def get_acc_list(self):
            return 0, [
                {"acc_id": "200", "acc_index": 1, "trd_env": "REAL"},
                {"acc_id": 100, "acc_index": 0, "trd_env": "SIMULATE"},
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyAccountClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_accounts() == (MoomooAccount("100", 0, "SIMULATE"), MoomooAccount("200", 1, "REAL"))
    assert context.closed is True
    assert not hasattr(client, "place_order")


def test_moomoo_read_only_account_client_fails_closed_for_broker_failure_or_malformed_data():
    class FailureContext:
        closed = False

        def get_acc_list(self):
            return 1, "broker failure"

        def close(self) -> None:
            self.closed = True

    class MalformedContext:
        closed = False

        def get_acc_list(self):
            return 0, [{"acc_id": "100", "acc_index": "zero", "trd_env": "REAL"}]

        def close(self) -> None:
            self.closed = True

    for context in (FailureContext(), MalformedContext()):
        client = MoomooReadOnlyAccountClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)
        with pytest.raises(VNextExternalDataError):
            client.list_accounts()
        assert context.closed is True


def test_moomoo_account_selection_requires_explicit_choice_when_ambiguous():
    accounts = (MoomooAccount("100", 0, "REAL"), MoomooAccount("200", 1, "REAL"))

    assert select_moomoo_account((MoomooAccount("100", 0, "REAL"),), None) == MoomooAccount("100", 0, "REAL")
    assert select_moomoo_account(accounts, "200") == MoomooAccount("200", 1, "REAL")
    with pytest.raises(VNextConfigurationError, match="account_id is required"):
        select_moomoo_account(accounts, None)
    with pytest.raises(VNextConfigurationError, match="is unavailable"):
        select_moomoo_account(accounts, "300")


def test_moomoo_read_only_balance_client_uses_stable_account_id_and_cached_read():
    class Context:
        closed = False
        kwargs: dict[str, object] = {}

        def accinfo_query(self, **kwargs):
            self.kwargs = kwargs
            return 0, [{"currency": "USD", "total_assets": 1500, "cash": 200.5, "market_val": 1299.5}]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyBalanceClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)
    account = MoomooAccount("100", 9, "REAL")

    assert client.read_balance(account) == MoomooAccountBalance("100", "USD", 1500.0, 200.5, 1299.5)
    assert context.kwargs == {"trd_env": "REAL", "acc_id": 100, "refresh_cache": False}
    assert context.closed is True
    assert not hasattr(client, "place_order")


def test_moomoo_read_only_balance_client_rejects_incomplete_or_nonfinite_broker_data():
    class Context:
        def accinfo_query(self, **kwargs):
            return 0, [{"currency": "USD", "total_assets": float("nan"), "cash": 2, "market_val": 3}]

        def close(self) -> None:
            pass

    client = MoomooReadOnlyBalanceClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.read_balance(MoomooAccount("100", 0, "REAL"))


def test_moomoo_read_only_position_client_uses_stable_account_id_and_cached_read():
    class Context:
        closed = False
        kwargs: dict[str, object] = {}

        def position_list_query(self, **kwargs):
            self.kwargs = kwargs
            return 0, [
                {"position_id": "two", "code": "US.MSFT", "qty": 2, "can_sell_qty": 1, "currency": "USD", "market_val": 800},
                {"position_id": "one", "code": "US.AAPL", "qty": 3, "can_sell_qty": 3, "currency": "USD", "market_val": 600},
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyPositionClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_positions(MoomooAccount("100", 0, "REAL")) == (
        MoomooPosition("100", "one", "US.AAPL", 3.0, 3.0, "USD", 600.0),
        MoomooPosition("100", "two", "US.MSFT", 2.0, 1.0, "USD", 800.0),
    )
    assert context.kwargs == {"trd_env": "REAL", "acc_id": 100, "refresh_cache": False}
    assert context.closed is True
    assert not hasattr(client, "place_order")


def test_moomoo_read_only_position_client_rejects_malformed_records():
    class Context:
        def position_list_query(self, **kwargs):
            return 0, [{"position_id": "one", "code": "US.AAPL", "qty": 1, "can_sell_qty": 1, "currency": "USD"}]

        def close(self) -> None:
            pass

    client = MoomooReadOnlyPositionClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.list_positions(MoomooAccount("100", 0, "REAL"))


def test_moomoo_read_only_open_order_client_preserves_chronological_read_output():
    class Context:
        closed = False
        kwargs: dict[str, object] = {}

        def order_list_query(self, **kwargs):
            self.kwargs = kwargs
            return 0, [
                {"order_id": "old", "code": "US.AAPL", "order_status": "SUBMITTING", "qty": 2, "dealt_qty": 0, "price": 200, "currency": "USD"},
                {"order_id": "new", "code": "US.MSFT", "order_status": "WAITING_SUBMIT", "qty": 3, "dealt_qty": 1, "price": 400, "currency": "USD"},
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyOpenOrderClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_open_orders(MoomooAccount("100", 0, "REAL")) == (
        MoomooOpenOrder("100", "old", "US.AAPL", "SUBMITTING", 2.0, 0.0, 200.0, "USD"),
        MoomooOpenOrder("100", "new", "US.MSFT", "WAITING_SUBMIT", 3.0, 1.0, 400.0, "USD"),
    )
    assert context.kwargs == {"trd_env": "REAL", "acc_id": 100, "refresh_cache": False}
    assert context.closed is True
    assert not hasattr(client, "place_order")


def test_moomoo_read_only_open_order_client_rejects_malformed_records():
    class Context:
        def order_list_query(self, **kwargs):
            return 0, [{"order_id": "old", "code": "US.AAPL", "order_status": "SUBMITTING", "qty": 2, "dealt_qty": 0, "price": float("nan"), "currency": "USD"}]

        def close(self) -> None:
            pass

    client = MoomooReadOnlyOpenOrderClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.list_open_orders(MoomooAccount("100", 0, "REAL"))


def test_moomoo_read_only_order_history_client_reads_explicit_window_with_stable_account_id():
    class Context:
        closed = False
        kwargs: dict[str, object] = {}

        def history_order_list_query(self, **kwargs):
            self.kwargs = kwargs
            return 0, [
                {
                    "order_id": "old",
                    "code": "US.AAPL",
                    "order_status": "CANCELLED_ALL",
                    "qty": 2,
                    "dealt_qty": 0,
                    "price": 200,
                    "currency": "USD",
                    "create_time": "2026-01-01 09:30:00",
                    "updated_time": "2026-01-01 09:31:00",
                }
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyOrderHistoryClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)
    window = MoomooOrderHistoryWindow("2026-01-01 00:00:00", "2026-01-02 00:00:00")

    assert client.list_order_history(MoomooAccount("100", 0, "REAL"), window) == (
        MoomooHistoricalOrder(
            "100", "old", "US.AAPL", "CANCELLED_ALL", 2.0, 0.0, 200.0, "USD", "2026-01-01 09:30:00", "2026-01-01 09:31:00"
        ),
    )
    assert context.kwargs == {
        "start": "2026-01-01 00:00:00",
        "end": "2026-01-02 00:00:00",
        "trd_env": "REAL",
        "acc_id": 100,
    }
    assert context.closed is True
    assert not hasattr(client, "place_order")


@pytest.mark.parametrize(
    "start,end",
    [("2026-01-02 00:00:00", "2026-01-01 00:00:00"), ("2026-01-01", "2026-01-02 00:00:00")],
)
def test_moomoo_order_history_window_rejects_invalid_or_reversed_bounds(start, end):
    with pytest.raises(ValueError):
        MoomooOrderHistoryWindow(start, end)


def test_moomoo_read_only_order_history_client_rejects_malformed_records():
    class Context:
        def history_order_list_query(self, **kwargs):
            return 0, [
                {
                    "order_id": "old",
                    "code": "US.AAPL",
                    "order_status": "CANCELLED_ALL",
                    "qty": 2,
                    "dealt_qty": 0,
                    "price": 200,
                    "currency": "USD",
                    "create_time": "2026-01-01 09:31:00",
                    "updated_time": "2026-01-01 09:30:00",
                }
            ]

        def close(self) -> None:
            pass

    client = MoomooReadOnlyOrderHistoryClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.list_order_history(
            MoomooAccount("100", 0, "REAL"), MoomooOrderHistoryWindow("2026-01-01 00:00:00", "2026-01-02 00:00:00")
        )


def test_moomoo_read_only_cash_flow_client_reads_live_account_by_clearing_date():
    class Context:
        closed = False
        kwargs: dict[str, object] = {}

        def get_acc_cash_flow(self, **kwargs):
            self.kwargs = kwargs
            return 0, [
                {
                    "cashflow_id": 10,
                    "clearing_date": "2026-01-01",
                    "settlement_date": "2026-01-03",
                    "currency": "USD",
                    "cashflow_type": "Fund Redemption",
                    "cashflow_direction": "IN",
                    "cashflow_amount": 2300,
                    "cashflow_remark": "fixture",
                }
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyCashFlowClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_cash_flows(MoomooAccount("100", 0, "REAL"), "2026-01-01") == (
        MoomooCashFlow("100", 10, "2026-01-01", "2026-01-03", "USD", "Fund Redemption", "IN", 2300.0, "fixture"),
    )
    assert context.kwargs == {"clearing_date": "2026-01-01", "trd_env": "REAL", "acc_id": 100}
    assert context.closed is True
    assert not hasattr(client, "place_order")


def test_moomoo_read_only_cash_flow_client_rejects_unsupported_or_malformed_broker_data():
    class Context:
        called = False

        def get_acc_cash_flow(self, **kwargs):
            self.called = True
            return 0, [
                {
                    "cashflow_id": 10,
                    "clearing_date": "2026-01-01",
                    "settlement_date": "2026-01-03",
                    "currency": "USD",
                    "cashflow_type": "Fund Redemption",
                    "cashflow_direction": "IN",
                    "cashflow_amount": float("nan"),
                    "cashflow_remark": "fixture",
                }
            ]

        def close(self) -> None:
            pass

    context = Context()
    client = MoomooReadOnlyCashFlowClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)
    with pytest.raises(VNextExternalDataError):
        client.list_cash_flows(MoomooAccount("100", 0, "SIMULATE"), "2026-01-01")
    assert context.called is False
    with pytest.raises(VNextExternalDataError):
        client.list_cash_flows(MoomooAccount("100", 0, "REAL"), "2026-01-01")


def test_moomoo_read_only_us_quote_client_reads_preexisting_subscriptions_only():
    class Context:
        closed = False
        symbols: list[str] = []

        def get_stock_quote(self, symbols):
            self.symbols = symbols
            return 0, [
                {
                    "code": "US.MSFT",
                    "data_date": "2026-01-01",
                    "data_time": "09:30:01.250",
                    "last_price": 400,
                    "open_price": 398,
                    "high_price": 401,
                    "low_price": 397,
                    "prev_close_price": 399,
                    "volume": 1000,
                    "turnover": 400000,
                    "suspension": False,
                },
                {
                    "code": "US.AAPL",
                    "data_date": "2026-01-01",
                    "data_time": "09:30:01.250",
                    "last_price": 200,
                    "open_price": 198,
                    "high_price": 201,
                    "low_price": 197,
                    "prev_close_price": 199,
                    "volume": 2000,
                    "turnover": 400000,
                    "suspension": False,
                },
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyUSQuoteClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_quotes(("US.AAPL", "US.MSFT")) == (
        MoomooUSQuote("US.AAPL", "2026-01-01", "09:30:01.250", 200.0, 198.0, 201.0, 197.0, 199.0, 2000.0, 400000.0, False),
        MoomooUSQuote("US.MSFT", "2026-01-01", "09:30:01.250", 400.0, 398.0, 401.0, 397.0, 399.0, 1000.0, 400000.0, False),
    )
    assert context.symbols == ["US.AAPL", "US.MSFT"]
    assert context.closed is True
    assert not hasattr(client, "subscribe")


@pytest.mark.parametrize("symbols", [(), ("SG.D05",), ("US.AAPL", "US.AAPL")])
def test_moomoo_read_only_us_quote_client_rejects_invalid_symbol_requests(symbols):
    client = MoomooReadOnlyUSQuoteClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: object())

    with pytest.raises(VNextExternalDataError):
        client.list_quotes(symbols)


def test_moomoo_read_only_us_quote_client_rejects_incomplete_or_nonfinite_data():
    class Context:
        def get_stock_quote(self, symbols):
            return 0, [
                {
                    "code": "US.AAPL",
                    "data_date": "2026-01-01",
                    "data_time": "09:30:01",
                    "last_price": float("nan"),
                    "open_price": 198,
                    "high_price": 201,
                    "low_price": 197,
                    "prev_close_price": 199,
                    "volume": 2000,
                    "turnover": 400000,
                    "suspension": False,
                }
            ]

        def close(self) -> None:
            pass

    client = MoomooReadOnlyUSQuoteClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.list_quotes(("US.AAPL", "US.MSFT"))


def test_moomoo_read_only_sg_quote_client_reads_preexisting_subscriptions_only():
    class Context:
        closed = False
        symbols: list[str] = []

        def get_stock_quote(self, symbols):
            self.symbols = symbols
            return 0, [
                {
                    "code": "SG.D05",
                    "data_date": "2026-01-01",
                    "data_time": "09:30:01",
                    "last_price": 36,
                    "open_price": 35.9,
                    "high_price": 36.1,
                    "low_price": 35.8,
                    "prev_close_price": 35.95,
                    "volume": 1000,
                    "turnover": 36000,
                    "suspension": False,
                }
            ]

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlySGQuoteClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_quotes(("SG.D05",)) == (
        MoomooSGQuote("SG.D05", "2026-01-01", "09:30:01", 36.0, 35.9, 36.1, 35.8, 35.95, 1000.0, 36000.0, False),
    )
    assert context.symbols == ["SG.D05"]
    assert context.closed is True
    assert not hasattr(client, "subscribe")


@pytest.mark.parametrize("symbols", [(), ("US.AAPL",), ("SG.D05", "SG.D05")])
def test_moomoo_read_only_sg_quote_client_rejects_invalid_symbol_requests(symbols):
    client = MoomooReadOnlySGQuoteClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: object())

    with pytest.raises(VNextExternalDataError):
        client.list_quotes(symbols)


def test_moomoo_read_only_sg_quote_client_rejects_malformed_data():
    class Context:
        def get_stock_quote(self, symbols):
            return 0, [
                {
                    "code": "SG.D05",
                    "data_date": "2026-01-01",
                    "data_time": "09:30:01",
                    "last_price": 36,
                    "open_price": 35.9,
                    "high_price": 36.1,
                    "low_price": 35.8,
                    "prev_close_price": 35.95,
                    "volume": 1000,
                    "turnover": float("nan"),
                    "suspension": False,
                }
            ]

        def close(self) -> None:
            pass

    client = MoomooReadOnlySGQuoteClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.list_quotes(("SG.D05",))


def test_moomoo_read_only_historical_candle_client_reads_single_complete_page():
    class Context:
        closed = False
        args: tuple[object, ...] = ()
        kwargs: dict[str, object] = {}

        def request_history_kline(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return 0, [
                {
                    "code": "US.AAPL",
                    "time_key": "2026-01-01 00:00:00",
                    "open": 100,
                    "close": 101,
                    "high": 102,
                    "low": 99,
                    "volume": 1000,
                    "turnover": 101000,
                    "last_close": 98,
                },
                {
                    "code": "US.AAPL",
                    "time_key": "2026-01-02 00:00:00",
                    "open": 101,
                    "close": 102,
                    "high": 103,
                    "low": 100,
                    "volume": 1200,
                    "turnover": 122400,
                    "last_close": 101,
                },
            ], None

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyHistoricalCandleClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context)

    assert client.list_daily_candles("US.AAPL", "2026-01-01", "2026-01-02") == (
        MoomooHistoricalCandle("US.AAPL", "2026-01-01 00:00:00", 100.0, 101.0, 102.0, 99.0, 1000.0, 101000.0, 98.0),
        MoomooHistoricalCandle("US.AAPL", "2026-01-02 00:00:00", 101.0, 102.0, 103.0, 100.0, 1200.0, 122400.0, 101.0),
    )
    assert context.args == ("US.AAPL",)
    assert context.kwargs == {"start": "2026-01-01", "end": "2026-01-02", "max_count": 1000}
    assert context.closed is True
    assert not hasattr(client, "subscribe")


@pytest.mark.parametrize("symbol,start,end", [("HK.00700", "2026-01-01", "2026-01-02"), ("US.AAPL", "2026-01-02", "2026-01-01")])
def test_moomoo_read_only_historical_candle_client_rejects_invalid_requests(symbol, start, end):
    client = MoomooReadOnlyHistoricalCandleClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: object())

    with pytest.raises(VNextExternalDataError):
        client.list_daily_candles(symbol, start, end)


def test_moomoo_read_only_historical_candle_client_rejects_pagination_or_malformed_data():
    class Context:
        def request_history_kline(self, *args, **kwargs):
            return 0, [], b"next-page"

        def close(self) -> None:
            pass

    client = MoomooReadOnlyHistoricalCandleClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError, match="pagination"):
        client.list_daily_candles("SG.D05", "2026-01-01", "2026-01-01")


def test_moomoo_read_only_market_data_entitlement_client_reads_all_connection_status():
    class Context:
        closed = False
        kwargs: dict[str, object] = {}

        def query_subscription(self, **kwargs):
            self.kwargs = kwargs
            return 0, {
                "total_used": 4,
                "own_used": 1,
                "remain": 996,
                "own_security_firm": "Moomoo SG",
                "sub_list": {"TICKER": ["US.AAPL"], "QUOTE": ["SG.D05", "US.AAPL"]},
            }

        def close(self) -> None:
            self.closed = True

    context = Context()
    client = MoomooReadOnlyMarketDataEntitlementClient(
        MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: context
    )

    assert client.read_entitlements() == MoomooMarketDataEntitlements(
        4,
        1,
        996,
        "Moomoo SG",
        (MoomooMarketDataSubscription("QUOTE", ("SG.D05", "US.AAPL")), MoomooMarketDataSubscription("TICKER", ("US.AAPL",))),
    )
    assert context.kwargs == {"is_all_conn": True}
    assert context.closed is True
    assert not hasattr(client, "subscribe")


def test_moomoo_read_only_market_data_entitlement_client_rejects_malformed_quota_data():
    class Context:
        def query_subscription(self, **kwargs):
            return 0, {"total_used": 1, "own_used": 2, "remain": 998, "own_security_firm": "Moomoo SG", "sub_list": {}}

        def close(self) -> None:
            pass

    client = MoomooReadOnlyMarketDataEntitlementClient(MoomooOpenDProcessContract("127.0.0.1", 11111), lambda host, port: Context())
    with pytest.raises(VNextExternalDataError):
        client.read_entitlements()


def test_normalize_moomoo_instruments_validates_and_sorts_us_sg_records():
    assert normalize_moomoo_instruments(
        [
            {"code": "US.AAPL", "name": "Apple", "lot_size": 1, "stock_type": "STOCK", "suspension": False},
            {"code": "SG.D05", "name": "DBS", "lot_size": 100, "stock_type": "STOCK", "suspension": False},
        ]
    ) == (
        MoomooInstrument("SG.D05", "DBS", 100, "STOCK", False),
        MoomooInstrument("US.AAPL", "Apple", 1, "STOCK", False),
    )


@pytest.mark.parametrize(
    "records",
    [
        [{"code": "HK.00700", "name": "Tencent", "lot_size": 100, "stock_type": "STOCK", "suspension": False}],
        [{"code": "US.AAPL", "name": "Apple", "lot_size": 0, "stock_type": "STOCK", "suspension": False}],
        [{"code": "US.AAPL", "name": "Apple", "lot_size": 1, "stock_type": "STOCK", "suspension": False}] * 2,
    ],
)
def test_normalize_moomoo_instruments_rejects_malformed_or_ambiguous_records(records):
    with pytest.raises(ValueError):
        normalize_moomoo_instruments(records)


def test_resolve_moomoo_us_equity_symbol_requires_canonical_moomoo_us_code():
    assert resolve_moomoo_us_equity_symbol("US.BRK.B") == "US.BRK.B"
    with pytest.raises(VNextExternalDataError, match="unresolved"):
        resolve_moomoo_us_equity_symbol("AAPL")
