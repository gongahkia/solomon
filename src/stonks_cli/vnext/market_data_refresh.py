from __future__ import annotations

from collections.abc import Callable, Sequence

from stonks_cli.config import AppConfig
from stonks_cli.vnext.capabilities import Capability, CapabilityRegistry
from stonks_cli.vnext.errors import VNextConfigurationError, VNextExecutionDeniedError, VNextExternalDataError
from stonks_cli.vnext.moomoo import (
    MoomooOpenDProcessContract,
    MoomooReadOnlyMarketDataEntitlementClient,
    MoomooReadOnlySGQuoteClient,
    MoomooReadOnlyUSQuoteClient,
    MoomooSdkCompatibility,
    MoomooSdkStatus,
    MoomooSGQuote,
    MoomooUSQuote,
    check_moomoo_sdk_compatibility,
    require_moomoo_data_entitlement,
    resolve_moomoo_sgx_equity_symbol,
    resolve_moomoo_us_equity_symbol,
)

MoomooQuote = MoomooUSQuote | MoomooSGQuote


def refresh_moomoo_market_data(
    config: AppConfig,
    symbols: Sequence[str],
    *,
    sdk_compatibility: Callable[[], MoomooSdkCompatibility] = check_moomoo_sdk_compatibility,
    context_factory: Callable[[str, int], object] | None = None,
) -> tuple[MoomooQuote, ...]:
    if not isinstance(config, AppConfig):
        raise TypeError("vNext app configuration is required")
    if not config.vnext.enabled or not config.vnext.moomoo.enabled:
        raise VNextConfigurationError("vNext Moomoo market-data refresh is not enabled")
    if config.vnext.moomoo.read_only is not True:
        raise VNextExecutionDeniedError("Moomoo market-data refresh requires read-only access")
    if not config.vnext.features.broker_data:
        raise VNextConfigurationError("vNext broker data capability is not enabled")
    CapabilityRegistry.from_feature_data(config.vnext.features.model_dump()).require(Capability.BROKER_DATA)
    normalized_symbols = _normalize_symbols(symbols)
    try:
        compatibility = sdk_compatibility()
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK compatibility is unavailable") from error
    if not isinstance(compatibility, MoomooSdkCompatibility):
        raise VNextExternalDataError("Moomoo SDK compatibility is malformed")
    if compatibility.status is not MoomooSdkStatus.COMPATIBLE:
        raise VNextExternalDataError(f"Moomoo SDK is unavailable:{compatibility.code}")
    factory = context_factory or _create_moomoo_quote_context
    contract = MoomooOpenDProcessContract(config.vnext.moomoo.host, config.vnext.moomoo.port)
    entitlements = MoomooReadOnlyMarketDataEntitlementClient(contract, factory).read_entitlements()
    require_moomoo_data_entitlement(entitlements, "QUOTE", normalized_symbols)
    quotes = _read_moomoo_quotes(contract, factory, normalized_symbols)
    return tuple(quotes[symbol] for symbol in normalized_symbols)


def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)) or not symbols:
        raise VNextExternalDataError("Moomoo market-data symbols must be a non-empty sequence")
    normalized: list[str] = []
    for symbol in symbols:
        if not isinstance(symbol, str):
            raise VNextExternalDataError("Moomoo market-data symbol is malformed")
        if symbol.startswith("US."):
            normalized.append(resolve_moomoo_us_equity_symbol(symbol))
        elif symbol.startswith("SG."):
            normalized.append(resolve_moomoo_sgx_equity_symbol(symbol))
        else:
            raise VNextExternalDataError("Moomoo market-data symbol is unresolved")
    if len(set(normalized)) != len(normalized):
        raise VNextExternalDataError("Moomoo market-data symbols must be unique")
    return tuple(normalized)


def _read_moomoo_quotes(
    contract: MoomooOpenDProcessContract, context_factory: Callable[[str, int], object], symbols: tuple[str, ...]
) -> dict[str, MoomooQuote]:
    us_symbols = tuple(symbol for symbol in symbols if symbol.startswith("US."))
    sg_symbols = tuple(symbol for symbol in symbols if symbol.startswith("SG."))
    quotes: dict[str, MoomooQuote] = {}
    if us_symbols:
        quotes.update({quote.symbol: quote for quote in MoomooReadOnlyUSQuoteClient(contract, context_factory).list_quotes(us_symbols)})
    if sg_symbols:
        quotes.update({quote.symbol: quote for quote in MoomooReadOnlySGQuoteClient(contract, context_factory).list_quotes(sg_symbols)})
    if set(quotes) != set(symbols):
        raise VNextExternalDataError("Moomoo market-data quote response is incomplete")
    return quotes


def _create_moomoo_quote_context(host: str, port: int) -> object:
    try:
        from moomoo import OpenQuoteContext
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK quote context is unavailable") from error
    try:
        return OpenQuoteContext(host=host, port=port)
    except Exception as error:
        raise VNextExternalDataError("Moomoo SDK quote context initialization failed") from error
