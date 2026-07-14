from __future__ import annotations

import math
import socket
import time
from dataclasses import dataclass
from enum import StrEnum

from stonks_cli.vnext.errors import VNextExecutionDeniedError

_LOCAL_OPEND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class MoomooOpenDProcessContract:
    host: str
    port: int
    operator_starts_gateway: bool = True
    operator_logs_in_gateway: bool = True
    cli_may_start_gateway: bool = False
    cli_may_unlock_trading: bool = False
    cli_may_submit_orders: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or self.host.lower() not in _LOCAL_OPEND_HOSTS:
            raise ValueError("OpenD process contract requires a local host")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("OpenD process contract requires a valid port")
        if not self.operator_starts_gateway or not self.operator_logs_in_gateway:
            raise ValueError("OpenD process contract requires operator-managed startup and login")
        if self.cli_may_start_gateway or self.cli_may_unlock_trading or self.cli_may_submit_orders:
            raise VNextExecutionDeniedError("OpenD contract prohibits CLI process, unlock, and order actions")

    def to_data(self) -> dict[str, object]:
        return {
            "host": self.host.lower(),
            "port": self.port,
            "operator_starts_gateway": self.operator_starts_gateway,
            "operator_logs_in_gateway": self.operator_logs_in_gateway,
            "cli_may_start_gateway": self.cli_may_start_gateway,
            "cli_may_unlock_trading": self.cli_may_unlock_trading,
            "cli_may_submit_orders": self.cli_may_submit_orders,
        }


class OpenDEndpointStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class OpenDEndpointProbe:
    status: OpenDEndpointStatus
    code: str
    latency_ms: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, OpenDEndpointStatus):
            raise TypeError("OpenD endpoint status is invalid")
        if self.status is OpenDEndpointStatus.AVAILABLE:
            if self.code != "available" or self.latency_ms is None or self.latency_ms < 0:
                raise ValueError("available OpenD probe requires latency")
        elif self.code != "connection_unavailable" or self.latency_ms is not None:
            raise ValueError("unavailable OpenD probe must not expose connection detail")


def probe_local_opend(contract: MoomooOpenDProcessContract, *, timeout_seconds: float = 1.0) -> OpenDEndpointProbe:
    if not isinstance(contract, MoomooOpenDProcessContract):
        raise TypeError("OpenD process contract is required")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise ValueError("OpenD probe timeout must be a positive finite number")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("OpenD probe timeout must be a positive finite number")
    started_at = time.perf_counter_ns()
    try:
        with socket.create_connection((contract.host, contract.port), timeout=timeout_seconds):
            pass
    except OSError:
        return OpenDEndpointProbe(OpenDEndpointStatus.UNAVAILABLE, "connection_unavailable", None)
    latency_ms = (time.perf_counter_ns() - started_at) / 1_000_000
    return OpenDEndpointProbe(OpenDEndpointStatus.AVAILABLE, "available", latency_ms)
