from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from typing import Protocol, runtime_checkable

from stonks_cli.errors import ExecutionDeniedError, ProviderError

PLUGIN_API_VERSION = 1


class Capability(StrEnum):
    ACCOUNTS = "accounts.read"
    BALANCES = "balances.read"
    POSITIONS = "positions.read"
    TRANSACTIONS = "transactions.read"
    CORPORATE_ACTIONS = "corporate_actions.read"
    MARKET_DATA = "market_data.read"


_FORBIDDEN = frozenset({"orders.write", "orders.read", "trade.unlock", "execution"})


@dataclass(frozen=True)
class PluginManifest:
    identifier: str
    api_version: int
    capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        if not self.identifier or self.api_version != PLUGIN_API_VERSION:
            raise ProviderError("incompatible plugin manifest")


@runtime_checkable
class ProviderPlugin(Protocol):
    manifest: PluginManifest


def validate_manifest(manifest: PluginManifest) -> None:
    if any(
        not isinstance(capability, Capability) or capability.value in _FORBIDDEN
        for capability in manifest.capabilities
    ):
        raise ExecutionDeniedError("execution capabilities are prohibited")


def discover() -> dict[str, ProviderPlugin]:
    selected = metadata.entry_points(group="stonks_cli.providers")
    providers: dict[str, ProviderPlugin] = {}
    for entry in selected:
        provider = entry.load()
        manifest = getattr(provider, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise ProviderError(f"plugin missing manifest:{entry.name}")
        validate_manifest(manifest)
        if manifest.identifier in providers:
            raise ProviderError(f"duplicate plugin:{manifest.identifier}")
        providers[manifest.identifier] = provider
    return providers
