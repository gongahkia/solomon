from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from stonks_cli.vnext.errors import VNextInvariantError

LifecycleCallback = Callable[[], None]


class LifecycleState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class LifecycleHook:
    name: str
    start: LifecycleCallback
    stop: LifecycleCallback

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("lifecycle hook name must be non-empty")
        if not callable(self.start) or not callable(self.stop):
            raise TypeError("lifecycle callbacks must be callable")


class ApplicationLifecycle:
    def __init__(self) -> None:
        self._hooks: list[LifecycleHook] = []
        self._started: list[LifecycleHook] = []
        self._state = LifecycleState.NEW

    @property
    def state(self) -> LifecycleState:
        return self._state

    def register(self, hook: LifecycleHook) -> None:
        if self._state is not LifecycleState.NEW:
            raise VNextInvariantError("lifecycle hooks can only be registered before startup")
        if any(existing.name == hook.name for existing in self._hooks):
            raise VNextInvariantError(f"lifecycle hook already registered:{hook.name}")
        self._hooks.append(hook)

    def start(self) -> None:
        if self._state is not LifecycleState.NEW:
            raise VNextInvariantError(f"lifecycle cannot start from state:{self._state}")
        try:
            for hook in self._hooks:
                hook.start()
                self._started.append(hook)
        except Exception:
            self._rollback_started_hooks()
            self._state = LifecycleState.FAILED
            raise
        self._state = LifecycleState.RUNNING

    def stop(self) -> None:
        if self._state is not LifecycleState.RUNNING:
            raise VNextInvariantError(f"lifecycle cannot stop from state:{self._state}")
        try:
            while self._started:
                self._started.pop().stop()
        finally:
            self._state = LifecycleState.STOPPED

    def _rollback_started_hooks(self) -> None:
        while self._started:
            try:
                self._started.pop().stop()
            except Exception:
                pass
