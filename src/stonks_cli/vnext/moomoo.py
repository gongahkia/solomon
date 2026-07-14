from __future__ import annotations

import math
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata, util

from stonks_cli.vnext.errors import VNextExecutionDeniedError, VNextExternalDataError

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


class MoomooSdkStatus(StrEnum):
    COMPATIBLE = "compatible"
    NOT_INSTALLED = "not_installed"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class MoomooSdkCompatibility:
    status: MoomooSdkStatus
    code: str
    version: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MoomooSdkStatus):
            raise TypeError("Moomoo SDK status is invalid")
        if self.status is MoomooSdkStatus.COMPATIBLE:
            if self.code != "sdk_compatible" or not self.version:
                raise ValueError("compatible Moomoo SDK check requires a version")
        elif self.version is not None:
            raise ValueError("incompatible Moomoo SDK check must not report a version")


def check_moomoo_sdk_compatibility(
    *,
    distribution_version: Callable[[str], str] = metadata.version,
    module_finder: Callable[[str], object | None] = util.find_spec,
) -> MoomooSdkCompatibility:
    try:
        version = distribution_version("moomoo-api")
    except metadata.PackageNotFoundError:
        return MoomooSdkCompatibility(MoomooSdkStatus.NOT_INSTALLED, "sdk_not_installed", None)
    except Exception:
        return MoomooSdkCompatibility(MoomooSdkStatus.INCOMPATIBLE, "sdk_metadata_unavailable", None)
    if not isinstance(version, str) or not version.strip():
        return MoomooSdkCompatibility(MoomooSdkStatus.INCOMPATIBLE, "sdk_invalid_version", None)
    try:
        module = module_finder("moomoo")
    except Exception:
        return MoomooSdkCompatibility(MoomooSdkStatus.INCOMPATIBLE, "sdk_module_unavailable", None)
    if module is None:
        return MoomooSdkCompatibility(MoomooSdkStatus.INCOMPATIBLE, "sdk_module_unavailable", None)
    return MoomooSdkCompatibility(MoomooSdkStatus.COMPATIBLE, "sdk_compatible", version.strip())


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


class LocalOpenDReadOnlyConnection:
    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection

    def __enter__(self) -> LocalOpenDReadOnlyConnection:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def receive(self, max_bytes: int = 65536) -> bytes:
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= 1_048_576:
            raise ValueError("OpenD receive size must be between 1 and 1048576 bytes")
        try:
            payload = self._connection.recv(max_bytes)
        except OSError as error:
            raise VNextExternalDataError("OpenD receive failed") from error
        if not payload:
            raise VNextExternalDataError("OpenD connection closed without read data")
        return payload

    def close(self) -> None:
        self._connection.close()


@dataclass(frozen=True)
class LocalOpenDReadOnlyClient:
    contract: MoomooOpenDProcessContract
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        _validate_timeout(self.timeout_seconds, message="OpenD client timeout must be a positive finite number")

    def connect(self) -> LocalOpenDReadOnlyConnection:
        try:
            connection = socket.create_connection((self.contract.host, self.contract.port), timeout=self.timeout_seconds)
        except OSError as error:
            raise VNextExternalDataError("OpenD connection unavailable") from error
        return LocalOpenDReadOnlyConnection(connection)


def _validate_timeout(timeout_seconds: object, *, message: str) -> None:
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise ValueError(message)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(message)
