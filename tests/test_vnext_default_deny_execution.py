from __future__ import annotations

import pytest

from stonks_cli.vnext.default_deny_execution import (
    DefaultDenyExecutionGateway,
    ExecutionDecision,
    ExecutionRequest,
)
from stonks_cli.vnext.errors import VNextExecutionDeniedError


def test_default_deny_execution_gateway_returns_a_non_permitting_decision():
    decision = DefaultDenyExecutionGateway().evaluate(ExecutionRequest("weekly-review-2026-07-14"))

    assert decision.permitted is False
    assert decision.reason == "execution gateway is disabled"
    with pytest.raises(VNextExecutionDeniedError, match="execution gateway is disabled"):
        decision.require_permitted()


@pytest.mark.parametrize("external_request", [None, "weekly-review-2026-07-14", {"request_id": "weekly-review-2026-07-14"}])
def test_default_deny_execution_gateway_rejects_malformed_external_requests(external_request):
    with pytest.raises(TypeError, match="requires an execution request"):
        DefaultDenyExecutionGateway().evaluate(external_request)  # type: ignore[arg-type]


@pytest.mark.parametrize("request_id", ["", "  ", None])
def test_execution_request_fails_closed_for_invalid_identifiers(request_id):
    with pytest.raises(ValueError, match="execution request ID is invalid"):
        ExecutionRequest(request_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("permitted,reason", [(True, "approved"), (False, ""), (False, None)])
def test_execution_decision_rejects_permitting_or_malformed_data(permitted, reason):
    with pytest.raises(ValueError):
        ExecutionDecision(permitted, reason)  # type: ignore[arg-type]
