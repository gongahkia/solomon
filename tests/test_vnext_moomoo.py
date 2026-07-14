from __future__ import annotations

import pytest

from stonks_cli.vnext.errors import VNextExecutionDeniedError
from stonks_cli.vnext.moomoo import MoomooOpenDProcessContract


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
