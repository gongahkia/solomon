from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.run_state import RunState, RunStateHistory


def test_run_state_history_models_start_failure_requeue_and_completion():
    run = RunStateHistory(UUID("00000000-0000-4000-8000-000000000001"))
    started = run.transition(RunState.RUNNING, datetime(2026, 7, 14, 2, tzinfo=UTC))
    failed = started.transition(RunState.FAILED, datetime(2026, 7, 14, 2, 1, tzinfo=UTC))
    requeued = failed.transition(RunState.PENDING, datetime(2026, 7, 14, 2, 2, tzinfo=UTC))
    completed = requeued.transition(RunState.RUNNING, datetime(2026, 7, 14, 2, 3, tzinfo=UTC)).transition(
        RunState.SUCCEEDED, datetime(2026, 7, 14, 2, 4, tzinfo=UTC)
    )

    assert completed.state is RunState.SUCCEEDED
    assert tuple(transition.to_state for transition in completed.transitions) == (
        RunState.RUNNING,
        RunState.FAILED,
        RunState.PENDING,
        RunState.RUNNING,
        RunState.SUCCEEDED,
    )


def test_run_state_history_fails_closed_for_invalid_or_nonchronological_transitions():
    run = RunStateHistory(UUID("00000000-0000-4000-8000-000000000001"))
    with pytest.raises(ValueError, match="not permitted"):
        run.transition(RunState.SUCCEEDED, datetime(2026, 7, 14, 2, tzinfo=UTC))
    started = run.transition(RunState.RUNNING, datetime(2026, 7, 14, 2, tzinfo=UTC))
    with pytest.raises(VNextInvariantError, match="moved backward"):
        started.transition(RunState.FAILED, datetime(2026, 7, 14, 2, tzinfo=UTC) - timedelta(seconds=1))
