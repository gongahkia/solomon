from __future__ import annotations

from collections.abc import Callable

from stonks_cli.vnext.health import HealthResult, HealthStatus
from stonks_cli.vnext.moomoo import (
    MoomooOpenDProcessContract,
    OpenDEndpointProbe,
    OpenDEndpointStatus,
    probe_local_opend,
)

OPEND_AVAILABILITY_HEALTH_CHECK = "opend.availability"


def monitor_opend_availability(
    contract: MoomooOpenDProcessContract,
    *,
    timeout_seconds: float = 1.0,
    probe: Callable[..., OpenDEndpointProbe] = probe_local_opend,
) -> HealthResult:
    if not isinstance(contract, MoomooOpenDProcessContract):
        raise TypeError("OpenD availability monitor requires a process contract")
    if not callable(probe):
        raise TypeError("OpenD availability monitor probe is invalid")
    result = probe(contract, timeout_seconds=timeout_seconds)
    if not isinstance(result, OpenDEndpointProbe):
        raise TypeError("OpenD availability monitor probe result is invalid")
    status = HealthStatus.PASS if result.status is OpenDEndpointStatus.AVAILABLE else HealthStatus.FAIL
    return HealthResult(OPEND_AVAILABILITY_HEALTH_CHECK, status, result.code)
