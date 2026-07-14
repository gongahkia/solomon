from __future__ import annotations

import math
import re
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from importlib import metadata, util

from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError

_LOCAL_OPEND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_MOOMOO_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")
_MOOMOO_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$")
_MOOMOO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MOOMOO_QUOTE_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$")
_MOOMOO_US_SYMBOL_PATTERN = re.compile(r"^US\.[A-Z0-9][A-Z0-9.-]*$")
_MOOMOO_SG_SYMBOL_PATTERN = re.compile(r"^SG\.[A-Z0-9][A-Z0-9.-]*$")


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
class MoomooCashFlow:
    account_id: str
    cashflow_id: int
    clearing_date: str
    settlement_date: str
    currency: str
    cashflow_type: str
    direction: str
    amount: float
    remark: str

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("Moomoo cash-flow account ID must be non-empty")
        if not isinstance(self.cashflow_id, int) or isinstance(self.cashflow_id, bool) or self.cashflow_id < 0:
            raise ValueError("Moomoo cash-flow ID must be a non-negative integer")
        _parse_moomoo_date(self.clearing_date)
        _parse_moomoo_date(self.settlement_date)
        if not all(isinstance(value, str) and value for value in (self.currency, self.cashflow_type, self.direction)):
            raise ValueError("Moomoo cash-flow fields must be non-empty")
        if not isinstance(self.amount, float) or not math.isfinite(self.amount):
            raise ValueError("Moomoo cash-flow amount must be finite")
        if not isinstance(self.remark, str):
            raise ValueError("Moomoo cash-flow remark must be a string")


@dataclass(frozen=True)
class MoomooReadOnlyCashFlowClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo cash-flow context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_cash_flows(self, account: MoomooAccount, clearing_date: str) -> tuple[MoomooCashFlow, ...]:
        if not isinstance(account, MoomooAccount) or not account.account_id.isdecimal():
            raise VNextExternalDataError("Moomoo selected account is malformed")
        if account.trading_environment != "REAL":
            raise VNextExternalDataError("Moomoo cash flow is unavailable for non-live accounts")
        try:
            _parse_moomoo_date(clearing_date)
        except ValueError as error:
            raise VNextExternalDataError("Moomoo cash-flow clearing date is malformed") from error
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo cash-flow context unavailable") from error
        try:
            getter = getattr(context, "get_acc_cash_flow", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo cash-flow context is incompatible")
            response = getter(clearing_date=clearing_date, trd_env=account.trading_environment, acc_id=int(account.account_id))
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo cash flow is unavailable")
            return _normalize_moomoo_cash_flows(account.account_id, clearing_date, response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo cash flow is malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo cash-flow context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo cash-flow context close failed") from error


def _normalize_moomoo_cash_flows(
    account_id: str, requested_clearing_date: str, raw_cash_flows: object
) -> tuple[MoomooCashFlow, ...]:
    records = raw_cash_flows
    to_dict = getattr(raw_cash_flows, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo cash flows must be a sequence")
    cash_flows: list[MoomooCashFlow] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo cash-flow record must be an object")
        cashflow_id = record.get("cashflow_id")
        clearing_date = record.get("clearing_date")
        settlement_date = record.get("settlement_date")
        currency = record.get("currency")
        cashflow_type = record.get("cashflow_type")
        direction = record.get("cashflow_direction")
        remark = record.get("cashflow_remark")
        if clearing_date != requested_clearing_date:
            raise ValueError("Moomoo cash-flow record has unexpected clearing date")
        if not isinstance(cashflow_id, int) or isinstance(cashflow_id, bool):
            raise ValueError("Moomoo cash-flow record has invalid ID")
        if not all(isinstance(value, str) for value in (clearing_date, settlement_date, currency, cashflow_type, direction, remark)):
            raise ValueError("Moomoo cash-flow record has invalid fields")
        cash_flows.append(
            MoomooCashFlow(
                account_id,
                cashflow_id,
                clearing_date,
                settlement_date,
                currency,
                cashflow_type,
                direction,
                _finite_cash_flow_amount(record),
                remark,
            )
        )
    if len({cash_flow.cashflow_id for cash_flow in cash_flows}) != len(cash_flows):
        raise ValueError("Moomoo cash-flow IDs must be unique")
    return tuple(cash_flows)


def _finite_cash_flow_amount(record: Mapping[object, object]) -> float:
    value = record.get("cashflow_amount")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Moomoo cash-flow record has invalid amount")
    return float(value)


def _parse_moomoo_date(value: object) -> date:
    if not isinstance(value, str) or not _MOOMOO_DATE_PATTERN.fullmatch(value):
        raise ValueError("Moomoo dates must use YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Moomoo date is invalid") from error


@dataclass(frozen=True)
class MoomooUSQuote:
    symbol: str
    quoted_date: str
    quoted_time: str
    last_price: float
    open_price: float
    high_price: float
    low_price: float
    previous_close_price: float
    volume: float
    turnover: float
    suspended: bool

    def __post_init__(self) -> None:
        _validate_moomoo_us_symbol(self.symbol)
        _parse_moomoo_date(self.quoted_date)
        _parse_moomoo_quote_time(self.quoted_time)
        for value in (
            self.last_price,
            self.open_price,
            self.high_price,
            self.low_price,
            self.previous_close_price,
            self.volume,
            self.turnover,
        ):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo US quote values must be finite floats")
        if not isinstance(self.suspended, bool):
            raise ValueError("Moomoo US quote suspension must be boolean")


@dataclass(frozen=True)
class MoomooReadOnlyUSQuoteClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo US quote context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_quotes(self, symbols: Sequence[str]) -> tuple[MoomooUSQuote, ...]:
        if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)) or not symbols:
            raise VNextExternalDataError("Moomoo US quote symbols must be a non-empty sequence")
        try:
            normalized_symbols = tuple(_validate_moomoo_us_symbol(symbol) for symbol in symbols)
        except ValueError as error:
            raise VNextExternalDataError("Moomoo US quote symbol is malformed") from error
        if len(set(normalized_symbols)) != len(normalized_symbols):
            raise VNextExternalDataError("Moomoo US quote symbols must be unique")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo US quote context unavailable") from error
        try:
            getter = getattr(context, "get_stock_quote", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo US quote context is incompatible")
            response = getter(list(normalized_symbols))
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo US quotes are unavailable")
            quotes = _normalize_moomoo_us_quotes(response[1], normalized_symbols)
            return tuple(quotes[symbol] for symbol in normalized_symbols)
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo US quotes are malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo US quote context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo US quote context close failed") from error


def _normalize_moomoo_us_quotes(raw_quotes: object, requested_symbols: Sequence[str]) -> dict[str, MoomooUSQuote]:
    records = raw_quotes
    to_dict = getattr(raw_quotes, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo US quotes must be a sequence")
    quotes: dict[str, MoomooUSQuote] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo US quote record must be an object")
        symbol = record.get("code")
        quoted_date = record.get("data_date")
        quoted_time = record.get("data_time")
        suspended = record.get("suspension")
        if (
            not isinstance(symbol, str)
            or not isinstance(quoted_date, str)
            or not isinstance(quoted_time, str)
            or not isinstance(suspended, bool)
        ):
            raise ValueError("Moomoo US quote record has invalid fields")
        if symbol not in requested_symbols or symbol in quotes:
            raise ValueError("Moomoo US quote response symbols are invalid")
        quotes[symbol] = MoomooUSQuote(
            symbol,
            quoted_date,
            quoted_time,
            _finite_quote_value(record, "last_price"),
            _finite_quote_value(record, "open_price"),
            _finite_quote_value(record, "high_price"),
            _finite_quote_value(record, "low_price"),
            _finite_quote_value(record, "prev_close_price"),
            _finite_quote_value(record, "volume"),
            _finite_quote_value(record, "turnover"),
            suspended,
        )
    if set(quotes) != set(requested_symbols):
        raise ValueError("Moomoo US quote response is incomplete")
    return quotes


@dataclass(frozen=True)
class MoomooSGQuote:
    symbol: str
    quoted_date: str
    quoted_time: str
    last_price: float
    open_price: float
    high_price: float
    low_price: float
    previous_close_price: float
    volume: float
    turnover: float
    suspended: bool

    def __post_init__(self) -> None:
        _validate_moomoo_sg_symbol(self.symbol)
        _parse_moomoo_date(self.quoted_date)
        _parse_moomoo_quote_time(self.quoted_time)
        for value in (
            self.last_price,
            self.open_price,
            self.high_price,
            self.low_price,
            self.previous_close_price,
            self.volume,
            self.turnover,
        ):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo SG quote values must be finite floats")
        if not isinstance(self.suspended, bool):
            raise ValueError("Moomoo SG quote suspension must be boolean")


@dataclass(frozen=True)
class MoomooReadOnlySGQuoteClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo SG quote context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def list_quotes(self, symbols: Sequence[str]) -> tuple[MoomooSGQuote, ...]:
        if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)) or not symbols:
            raise VNextExternalDataError("Moomoo SG quote symbols must be a non-empty sequence")
        try:
            normalized_symbols = tuple(_validate_moomoo_sg_symbol(symbol) for symbol in symbols)
        except ValueError as error:
            raise VNextExternalDataError("Moomoo SG quote symbol is malformed") from error
        if len(set(normalized_symbols)) != len(normalized_symbols):
            raise VNextExternalDataError("Moomoo SG quote symbols must be unique")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo SG quote context unavailable") from error
        try:
            getter = getattr(context, "get_stock_quote", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo SG quote context is incompatible")
            response = getter(list(normalized_symbols))
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo SG quotes are unavailable")
            quotes = _normalize_moomoo_sg_quotes(response[1], normalized_symbols)
            return tuple(quotes[symbol] for symbol in normalized_symbols)
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo SG quotes are malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo SG quote context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo SG quote context close failed") from error


def _normalize_moomoo_sg_quotes(raw_quotes: object, requested_symbols: Sequence[str]) -> dict[str, MoomooSGQuote]:
    records = raw_quotes
    to_dict = getattr(raw_quotes, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo SG quotes must be a sequence")
    quotes: dict[str, MoomooSGQuote] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo SG quote record must be an object")
        symbol = record.get("code")
        quoted_date = record.get("data_date")
        quoted_time = record.get("data_time")
        suspended = record.get("suspension")
        if (
            not isinstance(symbol, str)
            or not isinstance(quoted_date, str)
            or not isinstance(quoted_time, str)
            or not isinstance(suspended, bool)
        ):
            raise ValueError("Moomoo SG quote record has invalid fields")
        if symbol not in requested_symbols or symbol in quotes:
            raise ValueError("Moomoo SG quote response symbols are invalid")
        quotes[symbol] = MoomooSGQuote(
            symbol,
            quoted_date,
            quoted_time,
            _finite_quote_value(record, "last_price"),
            _finite_quote_value(record, "open_price"),
            _finite_quote_value(record, "high_price"),
            _finite_quote_value(record, "low_price"),
            _finite_quote_value(record, "prev_close_price"),
            _finite_quote_value(record, "volume"),
            _finite_quote_value(record, "turnover"),
            suspended,
        )
    if set(quotes) != set(requested_symbols):
        raise ValueError("Moomoo SG quote response is incomplete")
    return quotes


def _validate_moomoo_sg_symbol(symbol: object) -> str:
    if not isinstance(symbol, str) or not _MOOMOO_SG_SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Moomoo SG symbol must use the SG.TICKER format")
    return symbol


def _finite_quote_value(record: Mapping[object, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Moomoo US quote record has invalid {field}")
    return float(value)


def _validate_moomoo_us_symbol(symbol: object) -> str:
    if not isinstance(symbol, str) or not _MOOMOO_US_SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Moomoo US symbol must use the US.TICKER format")
    return symbol


def resolve_moomoo_us_equity_symbol(symbol: object) -> str:
    try:
        return _validate_moomoo_us_symbol(symbol)
    except ValueError as error:
        raise VNextExternalDataError("Moomoo US equity symbol is unresolved") from error


def _parse_moomoo_quote_time(value: object) -> None:
    if not isinstance(value, str) or not _MOOMOO_QUOTE_TIME_PATTERN.fullmatch(value):
        raise ValueError("Moomoo quote time must use HH:MM:SS[.ffffff]")
    for timestamp_format in ("%H:%M:%S", "%H:%M:%S.%f"):
        try:
            datetime.strptime(value, timestamp_format)
            return
        except ValueError:
            pass
    raise ValueError("Moomoo quote time is invalid")


@dataclass(frozen=True)
class MoomooHistoricalCandle:
    symbol: str
    time_key: str
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float
    turnover: float
    last_close_price: float

    def __post_init__(self) -> None:
        _validate_moomoo_us_or_sg_symbol(self.symbol)
        _parse_moomoo_timestamp(self.time_key)
        for value in (
            self.open_price,
            self.close_price,
            self.high_price,
            self.low_price,
            self.volume,
            self.turnover,
            self.last_close_price,
        ):
            if not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Moomoo historical candle values must be finite floats")
        if self.low_price > self.high_price or not self.low_price <= self.open_price <= self.high_price or not self.low_price <= self.close_price <= self.high_price:
            raise ValueError("Moomoo historical candle prices are inconsistent")


@dataclass(frozen=True)
class MoomooReadOnlyHistoricalCandleClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0
    max_count: int = 1000

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo historical-candle context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")
        if not isinstance(self.max_count, int) or isinstance(self.max_count, bool) or not 1 <= self.max_count <= 1000:
            raise ValueError("Moomoo historical-candle max_count must be within 1..1000")

    def list_daily_candles(self, symbol: str, start: str, end: str) -> tuple[MoomooHistoricalCandle, ...]:
        try:
            normalized_symbol = _validate_moomoo_us_or_sg_symbol(symbol)
            start_date = _parse_moomoo_date(start)
            end_date = _parse_moomoo_date(end)
        except ValueError as error:
            raise VNextExternalDataError("Moomoo historical-candle request is malformed") from error
        if end_date < start_date:
            raise VNextExternalDataError("Moomoo historical-candle end precedes start")
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo historical-candle context unavailable") from error
        try:
            getter = getattr(context, "request_history_kline", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo historical-candle context is incompatible")
            response = getter(normalized_symbol, start=start, end=end, max_count=self.max_count)
            if not isinstance(response, tuple) or len(response) != 3 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo historical candles are unavailable")
            if response[2] is not None:
                raise VNextExternalDataError("Moomoo historical candles require pagination")
            return _normalize_moomoo_historical_candles(normalized_symbol, start_date, end_date, response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo historical candles are malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo historical-candle context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo historical-candle context close failed") from error


def _normalize_moomoo_historical_candles(
    symbol: str, start_date: date, end_date: date, raw_candles: object
) -> tuple[MoomooHistoricalCandle, ...]:
    records = raw_candles
    to_dict = getattr(raw_candles, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo historical candles must be a sequence")
    candles: list[MoomooHistoricalCandle] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo historical-candle record must be an object")
        record_symbol = record.get("code")
        time_key = record.get("time_key")
        if not isinstance(record_symbol, str) or record_symbol != symbol or not isinstance(time_key, str):
            raise ValueError("Moomoo historical-candle record has invalid fields")
        candle_time = _parse_moomoo_timestamp(time_key)
        if not start_date <= candle_time.date() <= end_date:
            raise ValueError("Moomoo historical candle is outside requested bounds")
        candles.append(
            MoomooHistoricalCandle(
                symbol,
                time_key,
                _finite_candle_value(record, "open"),
                _finite_candle_value(record, "close"),
                _finite_candle_value(record, "high"),
                _finite_candle_value(record, "low"),
                _finite_candle_value(record, "volume"),
                _finite_candle_value(record, "turnover"),
                _finite_candle_value(record, "last_close"),
            )
        )
    if any(next_candle.time_key <= candle.time_key for candle, next_candle in zip(candles, candles[1:], strict=False)):
        raise ValueError("Moomoo historical candles must be chronological")
    return tuple(candles)


def _finite_candle_value(record: Mapping[object, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Moomoo historical-candle record has invalid {field}")
    return float(value)


def _validate_moomoo_us_or_sg_symbol(symbol: object) -> str:
    try:
        return _validate_moomoo_us_symbol(symbol)
    except ValueError:
        return _validate_moomoo_sg_symbol(symbol)


@dataclass(frozen=True)
class MoomooMarketDataSubscription:
    data_type: str
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.data_type, str) or not self.data_type:
            raise ValueError("Moomoo market-data subscription type must be non-empty")
        if not isinstance(self.symbols, tuple) or not all(isinstance(symbol, str) and symbol for symbol in self.symbols):
            raise ValueError("Moomoo market-data subscription symbols must be non-empty strings")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Moomoo market-data subscription symbols must be unique")


@dataclass(frozen=True)
class MoomooMarketDataEntitlements:
    total_used: int
    own_used: int
    remaining: int
    security_firm: str
    subscriptions: tuple[MoomooMarketDataSubscription, ...]

    def __post_init__(self) -> None:
        for value in (self.total_used, self.own_used, self.remaining):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("Moomoo market-data quotas must be non-negative integers")
        if self.own_used > self.total_used:
            raise ValueError("Moomoo own subscription quota exceeds total usage")
        if not isinstance(self.security_firm, str) or not self.security_firm:
            raise ValueError("Moomoo market-data security firm must be non-empty")
        if not isinstance(self.subscriptions, tuple) or not all(
            isinstance(subscription, MoomooMarketDataSubscription) for subscription in self.subscriptions
        ):
            raise ValueError("Moomoo market-data subscriptions are invalid")
        if len({subscription.data_type for subscription in self.subscriptions}) != len(self.subscriptions):
            raise ValueError("Moomoo market-data subscription types must be unique")


@dataclass(frozen=True)
class MoomooReadOnlyMarketDataEntitlementClient:
    contract: MoomooOpenDProcessContract
    context_factory: Callable[[str, int], object]
    success_code: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.contract, MoomooOpenDProcessContract):
            raise TypeError("OpenD process contract is required")
        if not callable(self.context_factory):
            raise TypeError("Moomoo entitlement context factory must be callable")
        if not isinstance(self.success_code, int) or isinstance(self.success_code, bool):
            raise ValueError("Moomoo SDK success code must be an integer")

    def read_entitlements(self) -> MoomooMarketDataEntitlements:
        try:
            context = self.context_factory(self.contract.host, self.contract.port)
        except Exception as error:
            raise VNextExternalDataError("Moomoo entitlement context unavailable") from error
        try:
            getter = getattr(context, "query_subscription", None)
            if not callable(getter):
                raise VNextExternalDataError("Moomoo entitlement context is incompatible")
            response = getter(is_all_conn=True)
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != self.success_code:
                raise VNextExternalDataError("Moomoo market-data entitlements are unavailable")
            return _normalize_moomoo_market_data_entitlements(response[1])
        except VNextExternalDataError:
            raise
        except Exception as error:
            raise VNextExternalDataError("Moomoo market-data entitlements are malformed") from error
        finally:
            closer = getattr(context, "close", None)
            if not callable(closer):
                raise VNextExternalDataError("Moomoo entitlement context is incompatible")
            try:
                closer()
            except Exception as error:
                raise VNextExternalDataError("Moomoo entitlement context close failed") from error


def _normalize_moomoo_market_data_entitlements(raw_entitlements: object) -> MoomooMarketDataEntitlements:
    if not isinstance(raw_entitlements, Mapping):
        raise ValueError("Moomoo market-data entitlements must be an object")
    total_used = raw_entitlements.get("total_used")
    own_used = raw_entitlements.get("own_used")
    remaining = raw_entitlements.get("remain")
    security_firm = raw_entitlements.get("own_security_firm")
    raw_subscriptions = raw_entitlements.get("sub_list")
    if (
        not isinstance(total_used, int)
        or isinstance(total_used, bool)
        or not isinstance(own_used, int)
        or isinstance(own_used, bool)
        or not isinstance(remaining, int)
        or isinstance(remaining, bool)
        or not isinstance(security_firm, str)
        or not isinstance(raw_subscriptions, Mapping)
    ):
        raise ValueError("Moomoo market-data entitlements have invalid fields")
    subscriptions: list[MoomooMarketDataSubscription] = []
    for data_type, raw_symbols in raw_subscriptions.items():
        if not isinstance(data_type, str) or not isinstance(raw_symbols, Sequence) or isinstance(raw_symbols, (str, bytes)):
            raise ValueError("Moomoo market-data subscription is malformed")
        subscriptions.append(MoomooMarketDataSubscription(data_type, tuple(raw_symbols)))
    return MoomooMarketDataEntitlements(total_used, own_used, remaining, security_firm, tuple(sorted(subscriptions, key=lambda item: item.data_type)))


@dataclass(frozen=True)
class MoomooInstrument:
    symbol: str
    display_name: str
    lot_size: int
    instrument_type: str
    suspended: bool

    def __post_init__(self) -> None:
        _validate_moomoo_us_or_sg_symbol(self.symbol)
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("Moomoo instrument display name must be non-empty")
        if not isinstance(self.lot_size, int) or isinstance(self.lot_size, bool) or self.lot_size <= 0:
            raise ValueError("Moomoo instrument lot size must be a positive integer")
        if not isinstance(self.instrument_type, str) or not self.instrument_type.strip():
            raise ValueError("Moomoo instrument type must be non-empty")
        if not isinstance(self.suspended, bool):
            raise ValueError("Moomoo instrument suspension must be boolean")


def normalize_moomoo_instruments(raw_instruments: object) -> tuple[MoomooInstrument, ...]:
    records = raw_instruments
    to_dict = getattr(raw_instruments, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("Moomoo instruments must be a sequence")
    instruments: list[MoomooInstrument] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Moomoo instrument record must be an object")
        symbol = record.get("code")
        display_name = record.get("name")
        lot_size = record.get("lot_size")
        instrument_type = record.get("stock_type")
        suspended = record.get("suspension")
        if not isinstance(symbol, str) or not isinstance(display_name, str) or not isinstance(lot_size, int) or isinstance(lot_size, bool):
            raise ValueError("Moomoo instrument record has invalid fields")
        if not isinstance(instrument_type, str) or not isinstance(suspended, bool):
            raise ValueError("Moomoo instrument record has invalid fields")
        instruments.append(MoomooInstrument(symbol, display_name, lot_size, instrument_type, suspended))
    if len({instrument.symbol for instrument in instruments}) != len(instruments):
        raise ValueError("Moomoo instrument symbols must be unique")
    return tuple(sorted(instruments, key=lambda instrument: instrument.symbol))


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
