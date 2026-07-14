from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.interrupted_run_recovery import recover_interrupted_run
from stonks_cli.vnext.run_state import RunState, RunStateHistory

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_interrupted_run_recovery_marks_running_work_failed_then_requeues_it():
    running = RunStateHistory(UUID("00000000-0000-4000-8000-000000000001")).transition(RunState.RUNNING, NOW)

    recovery = recover_interrupted_run(running, NOW + timedelta(minutes=1))

    assert recovery.recovered is True
    assert recovery.history.state is RunState.PENDING
    assert tuple(transition.to_state for transition in recovery.history.transitions) == (RunState.RUNNING, RunState.FAILED, RunState.PENDING)


def test_interrupted_run_recovery_keeps_nonrunning_work_unchanged_and_fails_closed_for_bad_input():
    pending = RunStateHistory(UUID("00000000-0000-4000-8000-000000000001"))

    assert recover_interrupted_run(pending, NOW).recovered is False
    with pytest.raises(TypeError, match="interrupted-run recovery"):
        recover_interrupted_run(None, NOW)  # type: ignore[arg-type]
    with pytest.raises(VNextInvariantError, match="timestamp moved backward"):
        recover_interrupted_run(pending.transition(RunState.RUNNING, NOW), NOW - timedelta(seconds=1))
