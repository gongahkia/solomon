from __future__ import annotations

import math
import re
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from importlib import metadata, util

from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError

_LOCAL_OPEND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_MOOMOO_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")
_MOOMOO_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$")


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
    trading_environment: str

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("Moomoo account ID must be non-empty")
        if not isinstance(self.account_index, int) or isinstance(self.account_index, bool) or self.account_index < 0:
            raise ValueError("Moomoo account index must be a non-negative integer")
        if not isinstance(self.trading_environment, str) or not self.trading_environment.strip():
            raise ValueError("Moomoo account trading environment must be non-empty")


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
        trading_environment = record.get("trd_env")
        if isinstance(account_id, bool) or not isinstance(account_id, (str, int)):
            raise ValueError("Moomoo account record has invalid ID")
        if not isinstance(account_index, int) or isinstance(account_index, bool) or account_index < 0:
            raise ValueError("Moomoo account record has invalid index")
        if not isinstance(trading_environment, str) or not trading_environment.strip():
            raise ValueError("Moomoo account record has invalid trading environment")
        accounts.append(MoomooAccount(str(account_id), account_index, trading_environment.strip()))
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
class MoomooAccountBalance:
    account_id: str
    currency: str
    total_assets: float
    cash: float
    market_value: float

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("Moomoo balance account ID must be non-empty")
        if not isinstance(self.currency, str) or not self.currency:
            raise ValueError("Moomoo balance currency must be non-empty")
        for value in (self.total_assets, self.cash, self.market_value):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo balance values must be finite floats")


@dataclass(frozen=True)
class MoomooReadOnlyBalanceClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo balance context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def read_balance(self, account: MoomooAccount) -> MoomooAccountBalance:
        if not isinstance(account, MoomooAccount) or not account.account_id.isdecimal():
            raise VNextExternalDataError("Moomoo selected account is malformed")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo balance context unavailable") from error
        try:
            getter = getattr(context, "accinfo_query", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo balance context is incompatible")
            response = getter(trd_env=account.trading_environment, acc_id=int(account.account_id), refresh_cache=False)
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo balance is unavailable")
            return _normalize_moomoo_balance(account.account_id, response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo balance is malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo balance context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo balance context close failed") from error


def _normalize_moomoo_balance(account_id: str, raw_balance: object) -> MoomooAccountBalance:
    records = raw_balance
    to_dict = getattr(raw_balance, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or len(records) != 1:
        raise ValueError("Moomoo balance must contain exactly one record")
    record = records[0]
    if not isinstance(record, Mapping):
        raise ValueError("Moomoo balance record must be an object")
    currency = record.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("Moomoo balance record has invalid currency")
    return MoomooAccountBalance(
        account_id,
        currency.strip(),
        _finite_balance_value(record, "total_assets"),
        _finite_balance_value(record, "cash"),
        _finite_balance_value(record, "market_val"),
    )


def _finite_balance_value(record: Mapping[object, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Moomoo balance record has invalid {field}")
    return float(value)


@dataclass(frozen=True)
class MoomooPosition:
    account_id: str
    position_id: str
    symbol: str
    quantity: float
    available_quantity: float
    currency: str
    market_value: float

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.position_id, self.symbol, self.currency)):
            raise ValueError("Moomoo position identifiers and currency must be non-empty")
        for value in (self.quantity, self.available_quantity, self.market_value):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo position values must be finite floats")


@dataclass(frozen=True)
class MoomooReadOnlyPositionClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo position context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_positions(self, account: MoomooAccount) -> tuple[MoomooPosition, ...]:
        if not isinstance(account, MoomooAccount) or not account.account_id.isdecimal():
            raise VNextExternalDataError("Moomoo selected account is malformed")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo position context unavailable") from error
        try:
            getter = getattr(context, "position_list_query", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo position context is incompatible")
            response = getter(trd_env=account.trading_environment, acc_id=int(account.account_id), refresh_cache=False)
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo positions are unavailable")
            return _normalize_moomoo_positions(account.account_id, response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo positions are malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo position context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo position context close failed") from error


def _normalize_moomoo_positions(account_id: str, raw_positions: object) -> tuple[MoomooPosition, ...]:
    records = raw_positions
    to_dict = getattr(raw_positions, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo positions must be a sequence")
    positions: list[MoomooPosition] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo position record must be an object")
        position_id = record.get("position_id")
        symbol = record.get("code")
        currency = record.get("currency")
        if not all(isinstance(value, str) and value for value in (position_id, symbol, currency)):
            raise ValueError("Moomoo position record has invalid identifiers")
        positions.append(
            MoomooPosition(
                account_id,
                position_id,
                symbol,
                _finite_position_value(record, "qty"),
                _finite_position_value(record, "can_sell_qty"),
                currency,
                _finite_position_value(record, "market_val"),
            )
        )
    if len({position.position_id for position in positions}) != len(positions):
        raise ValueError("Moomoo position IDs must be unique")
    return tuple(sorted(positions, key=lambda position: (position.symbol, position.position_id)))


def _finite_position_value(record: Mapping[object, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Moomoo position record has invalid {field}")
    return float(value)


@dataclass(frozen=True)
class MoomooOpenOrder:
    account_id: str
    order_id: str
    symbol: str
    status: str
    quantity: float
    dealt_quantity: float
    price: float
    currency: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.order_id, self.symbol, self.status, self.currency)):
            raise ValueError("Moomoo open order identifiers must be non-empty")
        for value in (self.quantity, self.dealt_quantity, self.price):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo open order values must be finite floats")


@dataclass(frozen=True)
class MoomooReadOnlyOpenOrderClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo open-order context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_open_orders(self, account: MoomooAccount) -> tuple[MoomooOpenOrder, ...]:
        if not isinstance(account, MoomooAccount) or not account.account_id.isdecimal():
            raise VNextExternalDataError("Moomoo selected account is malformed")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo open-order context unavailable") from error
        try:
            getter = getattr(context, "order_list_query", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo open-order context is incompatible")
            response = getter(trd_env=account.trading_environment, acc_id=int(account.account_id), refresh_cache=False)
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo open orders are unavailable")
            return _normalize_moomoo_open_orders(account.account_id, response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo open orders are malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo open-order context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo open-order context close failed") from error


def _normalize_moomoo_open_orders(account_id: str, raw_orders: object) -> tuple[MoomooOpenOrder, ...]:
    records = raw_orders
    to_dict = getattr(raw_orders, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo open orders must be a sequence")
    orders: list[MoomooOpenOrder] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo open-order record must be an object")
        order_id = record.get("order_id")
        symbol = record.get("code")
        status = record.get("order_status")
        currency = record.get("currency")
        if not all(isinstance(value, str) and value for value in (order_id, symbol, status, currency)):
            raise ValueError("Moomoo open-order record has invalid identifiers")
        orders.append(
            MoomooOpenOrder(
                account_id,
                order_id,
                symbol,
                status,
                _finite_open_order_value(record, "qty"),
                _finite_open_order_value(record, "dealt_qty"),
                _finite_open_order_value(record, "price"),
                currency,
            )
        )
    if len({order.order_id for order in orders}) != len(orders):
        raise ValueError("Moomoo open-order IDs must be unique")
    return tuple(orders)


def _finite_open_order_value(record: Mapping[object, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Moomoo open-order record has invalid {field}")
    return float(value)


@dataclass(frozen=True)
class MoomooOrderHistoryWindow:
    start: str
    end: str

    def __post_init__(self) -> None:
        start = _parse_moomoo_timestamp(self.start)
        end = _parse_moomoo_timestamp(self.end)
        if end <= start:
            raise ValueError("Moomoo order-history end must be after start")


@dataclass(frozen=True)
class MoomooHistoricalOrder:
    account_id: str
    order_id: str
    symbol: str
    status: str
    quantity: float
    dealt_quantity: float
    price: float
    currency: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.account_id, self.order_id, self.symbol, self.status, self.currency)
        ):
            raise ValueError("Moomoo historical order identifiers must be non-empty")
        for value in (self.quantity, self.dealt_quantity, self.price):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo historical order values must be finite floats")
        if _parse_moomoo_timestamp(self.updated_at) < _parse_moomoo_timestamp(self.created_at):
            raise ValueError("Moomoo historical order update predates creation")


@dataclass(frozen=True)
class MoomooReadOnlyOrderHistoryClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo order-history context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_order_history(
        self, account: MoomooAccount, window: MoomooOrderHistoryWindow
    ) -> tuple[MoomooHistoricalOrder, ...]:
        if not isinstance(account, MoomooAccount) or not account.account_id.isdecimal():
            raise VNextExternalDataError("Moomoo selected account is malformed")
        if not isinstance(window, MoomooOrderHistoryWindow):
            raise VNextExternalDataError("Moomoo order-history window is malformed")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo order-history context unavailable") from error
        try:
            getter = getattr(context, "history_order_list_query", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo order-history context is incompatible")
            response = getter(
                start=window.start,
                end=window.end,
                trd_env=account.trading_environment,
                acc_id=int(account.account_id),
            )
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo order history is unavailable")
            return _normalize_moomoo_historical_orders(account.account_id, response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo order history is malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo order-history context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo order-history context close failed") from error


def _normalize_moomoo_historical_orders(account_id: str, raw_orders: object) -> tuple[MoomooHistoricalOrder, ...]:
    records = raw_orders
    to_dict = getattr(raw_orders, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo historical orders must be a sequence")
    orders: list[MoomooHistoricalOrder] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo historical-order record must be an object")
        order_id = record.get("order_id")
        symbol = record.get("code")
        status = record.get("order_status")
        currency = record.get("currency")
        created_at = record.get("create_time")
        updated_at = record.get("updated_time")
        if not all(
            isinstance(value, str) and value
            for value in (order_id, symbol, status, currency, created_at, updated_at)
        ):
            raise ValueError("Moomoo historical-order record has invalid fields")
        orders.append(
            MoomooHistoricalOrder(
                account_id,
                order_id,
                symbol,
                status,
                _finite_open_order_value(record, "qty"),
                _finite_open_order_value(record, "dealt_qty"),
                _finite_open_order_value(record, "price"),
                currency,
                created_at,
                updated_at,
            )
        )
    if len({order.order_id for order in orders}) != len(orders):
        raise ValueError("Moomoo historical-order IDs must be unique")
    return tuple(orders)


def _parse_moomoo_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _MOOMOO_TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("Moomoo timestamps must use YYYY-MM-DD HH:MM:SS[.ffffff]")
    for timestamp_format in _MOOMOO_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, timestamp_format)
        except ValueError:
            pass
    raise ValueError("Moomoo timestamp is invalid")


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
