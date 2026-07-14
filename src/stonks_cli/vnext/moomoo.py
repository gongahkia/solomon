from __future__ import annotations

import math
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata, util

from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError

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


class MoomooTradeUnlockState(StrEnum):
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MoomooTradeUnlockEvidence:
    state: MoomooTradeUnlockState
    code: str
    secret_used: bool
    state_mutated: bool

    def __post_init__(self) -> None:
        if self.state is not MoomooTradeUnlockState.UNKNOWN:
            raise ValueError("Moomoo trade unlock state must remain unknown without a read API")
        if self.code != "state_not_observable_without_secret_or_mutation":
            raise ValueError("invalid Moomoo trade unlock evidence code")
        if self.secret_used or self.state_mutated:
            raise VNextExecutionDeniedError("Moomoo unlock evidence must not use secrets or mutate state")


def read_moomoo_trade_unlock_state_without_secrets() -> MoomooTradeUnlockEvidence:
    return MoomooTradeUnlockEvidence(
        MoomooTradeUnlockState.UNKNOWN,
        "state_not_observable_without_secret_or_mutation",
        secret_used=False,
        state_mutated=False,
    )


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
class MoomooAccount:
    account_id: str
    account_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("Moomoo account ID must be non-empty")
        if not isinstance(self.account_index, int) or isinstance(self.account_index, bool) or self.account_index < 0:
            raise ValueError("Moomoo account index must be a non-negative integer")


@dataclass(frozen=True)
class MoomooReadOnlyAccountClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo account context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_accounts(self) -> tuple[MoomooAccount, ...]:
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo account context unavailable") from error
        try:
            getter = getattr(context, "get_acc_list", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo account context is incompatible")
            response = getter()
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo account list is unavailable")
            return _normalize_moomoo_accounts(response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo account list is malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo account context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo account context close failed") from error


def _normalize_moomoo_accounts(raw_accounts: object) -> tuple[MoomooAccount, ...]:
    records = raw_accounts
    to_dict = getattr(raw_accounts, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo account records must be a sequence")
    accounts: list[MoomooAccount] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo account record must be an object")
        account_id = record.get("acc_id")
        account_index = record.get("acc_index")
        if isinstance(account_id, bool) or not isinstance(account_id, (str, int)):
            raise ValueError("Moomoo account record has invalid ID")
        if not isinstance(account_index, int) or isinstance(account_index, bool) or account_index < 0:
            raise ValueError("Moomoo account record has invalid index")
        accounts.append(MoomooAccount(str(account_id), account_index))
    if len({account.account_id for account in accounts}) != len(accounts):
        raise ValueError("Moomoo account IDs must be unique")
    if len({account.account_index for account in accounts}) != len(accounts):
        raise ValueError("Moomoo account indices must be unique")
    return tuple(sorted(accounts, key=lambda account: (account.account_index, account.account_id)))


def select_moomoo_account(accounts: Sequence[MoomooAccount], account_id: str | None) -> MoomooAccount:
    if not isinstance(accounts, Sequence) or isinstance(accounts, (str, bytes)):
        raise TypeError("Moomoo accounts must be a sequence")
    if not accounts:
        raise VNextExternalDataError("Moomoo account list is empty")
    if not all(isinstance(account, MoomooAccount) for account in accounts):
        raise VNextExternalDataError("Moomoo account list is malformed")
    if len({account.account_id for account in accounts}) != len(accounts):
        raise VNextExternalDataError("Moomoo account IDs are ambiguous")
    if account_id is None:
        if len(accounts) != 1:
            raise VNextConfigurationError("Moomoo account_id is required when multiple accounts are available")
        return accounts[0]
    if not isinstance(account_id, str) or not account_id.strip():
        raise VNextConfigurationError("Moomoo account_id is invalid")
    for account in accounts:
        if account.account_id == account_id.strip():
            return account
    raise VNextConfigurationError("Configured Moomoo account is unavailable")


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
