from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from typing import Protocol, runtime_checkable

from stonks_cli.errors import ExecutionDeniedError, ProviderError

PLUGIN_API_VERSION = "1.0.0"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


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
    api_version: str
    capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not (
            identifier := self.identifier.strip().lower()
        ):
            raise ProviderError("plugin identifier is required")
        if not _IDENTIFIER.fullmatch(identifier):
            raise ProviderError("plugin identifier is invalid")
        if not isinstance(self.api_version, str) or _api_version(self.api_version) is None:
            raise ProviderError("plugin API version is invalid")
        if not isinstance(self.capabilities, frozenset) or not self.capabilities:
            raise ProviderError("plugin capabilities are required")
        object.__setattr__(self, "identifier", identifier)


@runtime_checkable
class ProviderPlugin(Protocol):
    manifest: PluginManifest


def _api_version(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER.fullmatch(value)
    return (
        None
        if match is None
        else (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    )


def compatible_api_version(value: str) -> bool:
    plugin = _api_version(value)
    host = _api_version(PLUGIN_API_VERSION)
    if plugin is None or host is None:
        return False
    return plugin[0] == host[0] and plugin[1] <= host[1]


def validate_manifest(manifest: PluginManifest) -> None:
    if not compatible_api_version(manifest.api_version):
        raise ProviderError("incompatible plugin API version")
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
