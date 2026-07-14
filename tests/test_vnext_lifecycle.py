from __future__ import annotations

import pytest

from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.lifecycle import ApplicationLifecycle, LifecycleHook, LifecycleState


def test_application_lifecycle_starts_in_order_and_stops_in_reverse_order():
    events: list[str] = []
    lifecycle = ApplicationLifecycle()
    lifecycle.register(LifecycleHook("database", lambda: events.append("start:database"), lambda: events.append("stop:database")))
    lifecycle.register(LifecycleHook("reports", lambda: events.append("start:reports"), lambda: events.append("stop:reports")))

    lifecycle.start()
    lifecycle.stop()

    assert lifecycle.state is LifecycleState.STOPPED
    assert events == ["start:database", "start:reports", "stop:reports", "stop:database"]


def test_application_lifecycle_rolls_back_started_hooks_when_startup_fails():
    events: list[str] = []

    def start_broken() -> None:
        raise RuntimeError("startup failed")

    lifecycle = ApplicationLifecycle()
    lifecycle.register(LifecycleHook("database", lambda: events.append("start:database"), lambda: events.append("stop:database")))
    lifecycle.register(LifecycleHook("broken", start_broken, lambda: events.append("stop:broken")))

    with pytest.raises(RuntimeError, match="startup failed"):
        lifecycle.start()

    assert lifecycle.state is LifecycleState.FAILED
    assert events == ["start:database", "stop:database"]


def test_application_lifecycle_rejects_duplicate_and_invalid_state_transitions():
    lifecycle = ApplicationLifecycle()
    hook = LifecycleHook("database", lambda: None, lambda: None)
    lifecycle.register(hook)
    with pytest.raises(VNextInvariantError, match="already registered"):
        lifecycle.register(hook)
    with pytest.raises(VNextInvariantError, match="cannot stop from state:new"):
        lifecycle.stop()
    lifecycle.start()
    with pytest.raises(VNextInvariantError, match="cannot start from state:running"):
        lifecycle.start()
    with pytest.raises(VNextInvariantError, match="registered before startup"):
        lifecycle.register(LifecycleHook("reports", lambda: None, lambda: None))


def test_application_lifecycle_gracefully_runs_all_shutdown_hooks_when_one_fails():
    events: list[str] = []

    def broken_stop() -> None:
        events.append("stop:broken")
        raise RuntimeError("stop failed")

    lifecycle = ApplicationLifecycle()
    lifecycle.register(LifecycleHook("database", lambda: events.append("start:database"), lambda: events.append("stop:database")))
    lifecycle.register(LifecycleHook("reports", lambda: events.append("start:reports"), broken_stop))
    lifecycle.start()

    with pytest.raises(VNextInvariantError, match="shutdown encountered hook failures"):
        lifecycle.stop()

    assert lifecycle.state is LifecycleState.STOPPED
    assert events == ["start:database", "start:reports", "stop:broken", "stop:database"]
