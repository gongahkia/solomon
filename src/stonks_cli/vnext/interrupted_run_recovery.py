from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.run_state import RunState, RunStateHistory


@dataclass(frozen=True)
class InterruptedRunRecovery:
    history: RunStateHistory
    recovered: bool
    recovered_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.history, RunStateHistory):
            raise TypeError("interrupted-run recovery history is invalid")
        if not isinstance(self.recovered, bool):
            raise TypeError("interrupted-run recovery status is invalid")
        recovered_at = as_utc(self.recovered_at)
        if self.history.transitions and recovered_at < self.history.transitions[-1].transitioned_at:
            raise ValueError("interrupted-run recovery timestamp is invalid")
        if self.recovered and self.history.state is not RunState.PENDING:
            raise ValueError("interrupted-run recovery must requeue the run")
        object.__setattr__(self, "recovered_at", recovered_at)


def recover_interrupted_run(history: RunStateHistory, recovered_at: datetime) -> InterruptedRunRecovery:
    if not isinstance(history, RunStateHistory):
        raise TypeError("interrupted-run recovery requires run-state history")
    timestamp = as_utc(recovered_at)
    if history.state is not RunState.RUNNING:
        return InterruptedRunRecovery(history, False, timestamp)
    failed = history.transition(RunState.FAILED, timestamp)
    return InterruptedRunRecovery(failed.transition(RunState.PENDING, timestamp), True, timestamp)
