from __future__ import annotations

from collections.abc import Callable

from stonks_cli.config import AppConfig
from stonks_cli.vnext.capabilities import Capability, CapabilityRegistry
from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError
from stonks_cli.vnext.moomoo import (
    MoomooAccount,
    MoomooOpenDProcessContract,
    MoomooReadOnlyAccountClient,
    MoomooSdkCompatibility,
    MoomooSdkStatus,
    check_moomoo_sdk_compatibility,
)


def import_moomoo_accounts(
    config: AppConfig,
    *,
    sdk_compatibility: Callable[[], MoomooSdkCompatibility] = check_moomoo_sdk_compatibility,
    context_factory: Callable[[str, int], object] | None = None,
) -> tuple[MoomooAccount, ...]:
    if not isinstance(config, AppConfig):
        raise TypeError("vNext app configuration is required")
    if not config.vnext.enabled or not config.vnext.moomoo.enabled:
        raise VNextConfigurationError("vNext Moomoo account import is not enabled")
    if config.vnext.moomoo.read_only is not True:
        raise VNextExecutionDeniedError("Moomoo account import requires read-only access")
    if not config.vnext.features.broker_data:
        raise VNextConfigurationError("vNext broker data capability is not enabled")
    CapabilityRegistry.from_feature_data(config.vnext.features.model_dump()).require(Capability.BROKER_DATA)
    try:
        compatibility = sdk_compatibility()
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK compatibility is unavailable") from error
    if not isinstance(compatibility, MoomooSdkCompatibility):
        raise VNextExternalDataError("Moomoo SDK compatibility is malformed")
    if compatibility.status is not MoomooSdkStatus.COMPATIBLE:
        raise VNextExternalDataError(f"Moomoo SDK is unavailable:{compatibility.code}")
    factory = context_factory or _create_moomoo_security_trade_context
    client = MoomooReadOnlyAccountClient(
        MoomooOpenDProcessContract(config.vnext.moomoo.host, config.vnext.moomoo.port), factory
    )
    accounts = client.list_accounts()
    if not accounts:
        raise VNextExternalDataError("Moomoo account list is empty")
    return accounts


def _create_moomoo_security_trade_context(host: str, port: int) -> object:
    try:
        from moomoo import OpenSecTradeContext
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK context is unavailable") from error
    try:
        return OpenSecTradeContext(host=host, port=port)
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK context initialization failed") from error
