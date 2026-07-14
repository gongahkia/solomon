from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.execution_kill_switch import (
    DefaultClosedExecutionKillSwitch,
    EnvironmentExecutionKillSwitchAdapter,
    ExecutionKillSwitchState,
)

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_execution_kill_switch_adapter_defaults_closed_and_reports_explicit_environment_state():
    assert DefaultClosedExecutionKillSwitch().read_state(NOW) == ExecutionKillSwitchState(True, "default_closed", NOW)
    assert EnvironmentExecutionKillSwitchAdapter("STONKS_CLI_EXECUTION_KILL_SWITCH", {"STONKS_CLI_EXECUTION_KILL_SWITCH": "tripped"}).read_state(NOW).tripped is True
    assert EnvironmentExecutionKillSwitchAdapter("STONKS_CLI_EXECUTION_KILL_SWITCH", {"STONKS_CLI_EXECUTION_KILL_SWITCH": "clear"}).read_state(NOW).tripped is False


@pytest.mark.parametrize(
    "environment,reason",
    [
        ({}, "environment_unavailable"),
        ({"STONKS_CLI_EXECUTION_KILL_SWITCH": ""}, "environment_malformed"),
        ({"STONKS_CLI_EXECUTION_KILL_SWITCH": "enabled"}, "environment_malformed"),
    ],
)
def test_execution_kill_switch_adapter_fails_closed_for_missing_or_malformed_external_data(environment, reason):
    state = EnvironmentExecutionKillSwitchAdapter("STONKS_CLI_EXECUTION_KILL_SWITCH", environment).read_state(NOW)

    assert state == ExecutionKillSwitchState(True, reason, NOW)


@pytest.mark.parametrize("environment_variable", ["", "stonks_cli_execution_kill_switch", "STONKS-CLI-KILL-SWITCH"])
def test_execution_kill_switch_adapter_rejects_malformed_configuration(environment_variable):
    with pytest.raises(ValueError, match="environment variable"):
        EnvironmentExecutionKillSwitchAdapter(environment_variable)


@pytest.mark.parametrize("tripped,reason,observed_at", [("true", "default_closed", NOW), (True, "", NOW), (True, "default_closed", datetime(2026, 7, 14, 3))])
def test_execution_kill_switch_state_rejects_malformed_data(tripped, reason, observed_at):
    with pytest.raises((TypeError, ValueError)):
        ExecutionKillSwitchState(tripped, reason, observed_at)  # type: ignore[arg-type]
