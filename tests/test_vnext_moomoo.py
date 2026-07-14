from __future__ import annotations

import socket

import pytest

from stonks_cli.vnext.errors import VNextExecutionDeniedError
from stonks_cli.vnext.moomoo import MoomooOpenDProcessContract, OpenDEndpointStatus, probe_local_opend


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
