from __future__ import annotations

import json

import pytest

from stonks_cli.errors import ExitCodes, StonksError
from stonks_cli.vnext.errors import (
    VNextApplicationError,
    VNextConfigurationError,
    VNextExecutionDeniedError,
    VNextExternalDataError,
    VNextInvariantError,
)


@pytest.mark.parametrize(
    ("error_type", "exit_code", "public_code"),
    [
        (VNextConfigurationError, ExitCodes.BAD_CONFIG, "vnext.configuration.invalid"),
        (VNextExternalDataError, ExitCodes.PROVIDER_ERROR, "vnext.external_data.unavailable"),
        (VNextInvariantError, ExitCodes.UNKNOWN_ERROR, "vnext.invariant.failed"),
        (VNextExecutionDeniedError, ExitCodes.USAGE_ERROR, "vnext.execution.denied"),
    ],
)
def test_vnext_error_hierarchy_has_stable_safe_contract(error_type, exit_code, public_code):
    error = error_type("internal token-value detail")

    assert isinstance(error, (VNextApplicationError, StonksError))
    assert error.code == exit_code
    assert error.to_data()["error"]["code"] == public_code
    assert "token-value" not in json.dumps(error.to_data())


def test_vnext_error_uses_public_message_when_no_internal_detail_is_available():
    error = VNextExecutionDeniedError()

    assert str(error) == "vNext execution is disabled."
