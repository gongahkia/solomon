from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from stonks_cli.vnext.errors import VNextExecutionDeniedError


@dataclass(frozen=True)
class ExecutionRequest:
    """Opaque pre-execution request; it contains no broker credentials or submission data."""

    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("execution request ID is invalid")


@dataclass(frozen=True)
class ExecutionDecision:
    permitted: bool
    reason: str

    def __post_init__(self) -> None:
        if self.permitted is not False:
            raise ValueError("vNext execution decisions must deny by default")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("execution denial reason is invalid")

    def require_permitted(self) -> None:
        raise VNextExecutionDeniedError(self.reason)


class ExecutionGateway(Protocol):
    def evaluate(self, request: ExecutionRequest) -> ExecutionDecision: ...


class DefaultDenyExecutionGateway:
    """Stable deferred-execution seam that cannot authorize broker actions."""

    _DENIAL_REASON = "execution gateway is disabled"

    def evaluate(self, request: ExecutionRequest) -> ExecutionDecision:
        if not isinstance(request, ExecutionRequest):
            raise TypeError("execution gateway requires an execution request")
        return ExecutionDecision(permitted=False, reason=self._DENIAL_REASON)
