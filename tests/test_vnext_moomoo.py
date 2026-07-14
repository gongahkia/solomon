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
    MoomooHistoricalOrder,
    MoomooOpenDProcessContract,
    MoomooOpenOrder,
    MoomooOrderHistoryWindow,
    MoomooPosition,
    MoomooReadOnlyAccountClient,
    MoomooReadOnlyBalanceClient,
    MoomooReadOnlyOpenOrderClient,
    MoomooReadOnlyOrderHistoryClient,
    MoomooReadOnlyPositionClient,
    MoomooSdkStatus,
    MoomooTradeUnlockState,
    OpenDEndpointStatus,
    check_moomoo_sdk_compatibility,
    probe_local_opend,
    read_moomoo_trade_unlock_state_without_secrets,
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
