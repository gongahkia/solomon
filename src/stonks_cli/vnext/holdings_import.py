from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from stonks_cli.config import AppConfig
from stonks_cli.vnext.capabilities import Capability, CapabilityRegistry
from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError
from stonks_cli.vnext.moomoo import (
    MoomooAccount,
    MoomooOpenDProcessContract,
    MoomooPosition,
    MoomooReadOnlyPositionClient,
    MoomooSdkCompatibility,
    MoomooSdkStatus,
    check_moomoo_sdk_compatibility,
)
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot


def import_moomoo_holdings(
    config: AppConfig,
    account: MoomooAccount,
    captured_at: datetime,
    *,
    sdk_compatibility: Callable[[], MoomooSdkCompatibility] = check_moomoo_sdk_compatibility,
    context_factory: Callable[[str, int], object] | None = None,
) -> PortfolioSnapshot:
    if not isinstance(config, AppConfig):
        raise TypeError("vNext app configuration is required")
    if not isinstance(account, MoomooAccount):
        raise TypeError("Moomoo account is required")
    if not config.vnext.enabled or not config.vnext.moomoo.enabled:
        raise VNextConfigurationError("vNext Moomoo holdings import is not enabled")
    if config.vnext.moomoo.read_only is not True:
        raise VNextExecutionDeniedError("Moomoo holdings import requires read-only access")
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
    positions = MoomooReadOnlyPositionClient(
        MoomooOpenDProcessContract(config.vnext.moomoo.host, config.vnext.moomoo.port), factory
    ).list_positions(account)
    try:
        holdings = tuple(_holding_from_moomoo_position(position) for position in positions)
        return PortfolioSnapshot("moomoo", account.account_id, captured_at, holdings)
    except (TypeError, ValueError) as error:
        raise VNextExternalDataError(f"Moomoo holdings are malformed:{error}") from error


def _holding_from_moomoo_position(position: MoomooPosition) -> PortfolioHolding:
    if not isinstance(position, MoomooPosition):
        raise TypeError("Moomoo position is invalid")
    if not position.symbol.startswith(("US.", "SG.")):
        raise ValueError("Moomoo holding asset class is unsupported")
    return PortfolioHolding(
        position.account_id,
        position.position_id,
        position.symbol,
        PortfolioAssetClass.EQUITY,
        position.quantity,
        position.currency,
        position.market_value,
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
