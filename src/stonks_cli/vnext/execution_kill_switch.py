from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from stonks_cli.vnext.foundation import as_utc

_ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*\Z")


@dataclass(frozen=True)
class ExecutionKillSwitchState:
    tripped: bool
    reason: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.tripped, bool):
            raise TypeError("execution kill-switch state is invalid")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("execution kill-switch reason is invalid")
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


class ExecutionKillSwitchAdapter(Protocol):
    def read_state(self, observed_at: datetime) -> ExecutionKillSwitchState: ...


class DefaultClosedExecutionKillSwitch:
    """Default-safe adapter; a clear state never authorizes broker execution."""

    def read_state(self, observed_at: datetime) -> ExecutionKillSwitchState:
        return ExecutionKillSwitchState(True, "default_closed", observed_at)


@dataclass(frozen=True)
class EnvironmentExecutionKillSwitchAdapter:
    environment_variable: str
    environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.environment_variable, str) or not _ENVIRONMENT_VARIABLE_PATTERN.fullmatch(self.environment_variable):
            raise ValueError("execution kill-switch environment variable is invalid")
        if self.environment is not None and not isinstance(self.environment, Mapping):
            raise TypeError("execution kill-switch environment is invalid")

    def read_state(self, observed_at: datetime) -> ExecutionKillSwitchState:
        environment = os.environ if self.environment is None else self.environment
        value = environment.get(self.environment_variable)
        if value == "clear":
            return ExecutionKillSwitchState(False, "environment_clear", observed_at)
        if value == "tripped":
            return ExecutionKillSwitchState(True, "environment_tripped", observed_at)
        if value is None:
            return ExecutionKillSwitchState(True, "environment_unavailable", observed_at)
        return ExecutionKillSwitchState(True, "environment_malformed", observed_at)
