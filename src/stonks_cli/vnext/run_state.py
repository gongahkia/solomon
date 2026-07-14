from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.foundation import as_utc


class RunState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_NEXT_STATES = {
    RunState.PENDING: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.RUNNING: frozenset({RunState.PENDING, RunState.SUCCEEDED, RunState.FAILED}),
    RunState.FAILED: frozenset({RunState.PENDING, RunState.CANCELLED}),
    RunState.SUCCEEDED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class RunStateTransition:
    run_id: UUID
    from_state: RunState
    to_state: RunState
    transitioned_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise TypeError("run-state transition run ID must be a UUID")
        if not isinstance(self.from_state, RunState) or not isinstance(self.to_state, RunState):
            raise TypeError("run-state transition states are invalid")
        if self.to_state not in _ALLOWED_NEXT_STATES[self.from_state]:
            raise ValueError(f"run-state transition is not permitted:{self.from_state}->{self.to_state}")
        object.__setattr__(self, "transitioned_at", as_utc(self.transitioned_at))


@dataclass(frozen=True)
class RunStateHistory:
    run_id: UUID
    transitions: tuple[RunStateTransition, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise TypeError("run-state history run ID must be a UUID")
        if not isinstance(self.transitions, tuple) or not all(isinstance(item, RunStateTransition) for item in self.transitions):
            raise ValueError("run-state history transitions are invalid")
        state = RunState.PENDING
        previous_at: datetime | None = None
        for transition in self.transitions:
            if transition.run_id != self.run_id or transition.from_state is not state:
                raise ValueError("run-state history transitions are inconsistent")
            if previous_at is not None and transition.transitioned_at < previous_at:
                raise ValueError("run-state history transitions are not chronological")
            state = transition.to_state
            previous_at = transition.transitioned_at

    @property
    def state(self) -> RunState:
        return RunState.PENDING if not self.transitions else self.transitions[-1].to_state

    def transition(self, to_state: RunState, transitioned_at: datetime) -> RunStateHistory:
        transition = RunStateTransition(self.run_id, self.state, to_state, transitioned_at)
        if self.transitions and transition.transitioned_at < self.transitions[-1].transitioned_at:
            raise VNextInvariantError("run-state transition timestamp moved backward")
        return RunStateHistory(self.run_id, self.transitions + (transition,))
