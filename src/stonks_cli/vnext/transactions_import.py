from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from stonks_cli.config import AppConfig
from stonks_cli.vnext.capabilities import Capability, CapabilityRegistry
from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError
from stonks_cli.vnext.exchange_time import ExchangeTimeZone, normalize_exchange_timestamp
from stonks_cli.vnext.moomoo import (
    MoomooAccount,
    MoomooHistoricalOrder,
    MoomooOpenDProcessContract,
    MoomooOrderHistoryWindow,
    MoomooReadOnlyOrderHistoryClient,
    MoomooSdkCompatibility,
    MoomooSdkStatus,
    check_moomoo_sdk_compatibility,
)

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")
_SUPPORTED_SYMBOL_PREFIXES = {
    ExchangeTimeZone.SINGAPORE: "SG.",
    ExchangeTimeZone.US_EASTERN: "US.",
}


class PortfolioTransactionSide(StrEnum):
    BUY = "BUY"
    BUY_BACK = "BUY_BACK"
    SELL = "SELL"
    SELL_SHORT = "SELL_SHORT"


@dataclass(frozen=True)
class PortfolioTransaction:
    account_id: str
    transaction_id: str
    symbol: str
    side: PortfolioTransactionSide
    quantity: float
    unit_price: float
    currency: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.transaction_id, self.symbol)):
            raise ValueError("portfolio transaction identifiers are invalid")
        if not isinstance(self.side, PortfolioTransactionSide):
            raise ValueError("portfolio transaction side is invalid")
        if not isinstance(self.quantity, float) or not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("portfolio transaction quantity is invalid")
        if not isinstance(self.unit_price, float) or not math.isfinite(self.unit_price) or self.unit_price <= 0:
            raise ValueError("portfolio transaction unit price is invalid")
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("portfolio transaction currency is invalid")
        if not isinstance(self.recorded_at, datetime) or self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("portfolio transaction timestamp is invalid")


def import_moomoo_transactions(
    config: AppConfig,
    account: MoomooAccount,
    window: MoomooOrderHistoryWindow,
    exchange_time_zone: ExchangeTimeZone,
    *,
    sdk_compatibility: Callable[[], MoomooSdkCompatibility] = check_moomoo_sdk_compatibility,
    context_factory: Callable[[str, int], object] | None = None,
) -> tuple[PortfolioTransaction, ...]:
    if not isinstance(config, AppConfig):
        raise TypeError("vNext app configuration is required")
    if not isinstance(account, MoomooAccount) or not isinstance(window, MoomooOrderHistoryWindow):
        raise TypeError("Moomoo account and order-history window are required")
    if not isinstance(exchange_time_zone, ExchangeTimeZone):
        raise TypeError("exchange time zone is required")
    if not config.vnext.enabled or not config.vnext.moomoo.enabled:
        raise VNextConfigurationError("vNext Moomoo transaction import is not enabled")
    if config.vnext.moomoo.read_only is not True:
        raise VNextExecutionDeniedError("Moomoo transaction import requires read-only access")
    if not config.vnext.features.broker_data or not config.vnext.features.portfolio:
        raise VNextConfigurationError("vNext broker-data and portfolio capabilities are required")
    capabilities = CapabilityRegistry.from_feature_data(config.vnext.features.model_dump())
    capabilities.require(Capability.BROKER_DATA)
    capabilities.require(Capability.PORTFOLIO)
    try:
        compatibility = sdk_compatibility()
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK compatibility is unavailable") from error
    if not isinstance(compatibility, MoomooSdkCompatibility):
        raise VNextExternalDataError("Moomoo SDK compatibility is malformed")
    if compatibility.status is not MoomooSdkStatus.COMPATIBLE:
        raise VNextExternalDataError(f"Moomoo SDK is unavailable:{compatibility.code}")
    factory = context_factory or _create_moomoo_security_trade_context
    orders = MoomooReadOnlyOrderHistoryClient(
        MoomooOpenDProcessContract(config.vnext.moomoo.host, config.vnext.moomoo.port), factory
    ).list_order_history(account, window)
    try:
        transactions = tuple(_transaction_from_moomoo_order(order, exchange_time_zone) for order in orders if order.status == "FILLED_ALL")
        if any(order.status in {"FILLED_PART", "CANCELLED_PART"} or order.dealt_quantity > 0 and order.status != "FILLED_ALL" for order in orders):
            raise ValueError("Moomoo transaction import has incomplete fills")
        if len({transaction.transaction_id for transaction in transactions}) != len(transactions):
            raise ValueError("Moomoo transaction IDs are ambiguous")
        return tuple(sorted(transactions, key=lambda transaction: (transaction.recorded_at, transaction.transaction_id)))
    except (TypeError, ValueError) as error:
        raise VNextExternalDataError(f"Moomoo transactions are malformed:{error}") from error


def _transaction_from_moomoo_order(order: MoomooHistoricalOrder, exchange_time_zone: ExchangeTimeZone) -> PortfolioTransaction:
    if not isinstance(order, MoomooHistoricalOrder):
        raise TypeError("Moomoo historical order is invalid")
    if order.status != "FILLED_ALL" or order.dealt_quantity != order.quantity or order.dealt_quantity <= 0:
        raise ValueError("Moomoo transaction order is incomplete")
    if not order.symbol.startswith(_SUPPORTED_SYMBOL_PREFIXES[exchange_time_zone]):
        raise ValueError("Moomoo transaction symbol does not match exchange time zone")
    try:
        side = PortfolioTransactionSide(order.side)
    except ValueError as error:
        raise ValueError("Moomoo transaction side is unsupported") from error
    return PortfolioTransaction(
        order.account_id,
        order.order_id,
        order.symbol,
        side,
        order.dealt_quantity,
        order.dealt_average_price,
        order.currency,
        normalize_exchange_timestamp(order.updated_at, exchange_time_zone),
    )


def _create_moomoo_security_trade_context(host: str, port: int) -> object:
    try:
        from moomoo import OpenSecTradeContext
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK context is unavailable") from error
    try:
        return OpenSecTradeContext(host=host, port=port)
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK context initialization failed") from error
