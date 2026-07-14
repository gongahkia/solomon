from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

_HEALTH_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_.]*\Z")


class HealthStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class HealthResult:
    name: str
    status: HealthStatus
    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _HEALTH_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("invalid health check name")
        if not isinstance(self.status, HealthStatus):
            raise TypeError("health result status must be a HealthStatus")
        if not isinstance(self.code, str) or not _HEALTH_NAME_PATTERN.fullmatch(self.code):
            raise ValueError("invalid health result code")


HealthCheckCallback = Callable[[], HealthStatus | HealthResult]


@dataclass(frozen=True)
class HealthCheck:
    name: str
    check: HealthCheckCallback

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _HEALTH_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("invalid health check name")
        if not callable(self.check):
            raise TypeError("health check must be callable")


@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    results: tuple[HealthResult, ...]


def run_health_checks(checks: Iterable[HealthCheck]) -> HealthReport:
    ordered_checks = tuple(checks)
    names = tuple(check.name for check in ordered_checks)
    if len(set(names)) != len(names):
        raise ValueError("health check names must be unique")
    results = tuple(_run_health_check(check) for check in ordered_checks)
    return HealthReport(_aggregate_status(results), results)


def _run_health_check(check: HealthCheck) -> HealthResult:
    try:
        result = check.check()
    except Exception:
        return HealthResult(check.name, HealthStatus.FAIL, "check_error")
    if isinstance(result, HealthStatus):
        return HealthResult(check.name, result, result.value)
    if isinstance(result, HealthResult) and result.name == check.name:
        return result
    return HealthResult(check.name, HealthStatus.FAIL, "invalid_result")


def _aggregate_status(results: tuple[HealthResult, ...]) -> HealthStatus:
    if any(result.status is HealthStatus.FAIL for result in results):
        return HealthStatus.FAIL
    if any(result.status is HealthStatus.WARNING for result in results):
        return HealthStatus.WARNING
    return HealthStatus.PASS
