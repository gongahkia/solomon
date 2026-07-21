from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from typing import Protocol, runtime_checkable

from stonks_cli.errors import ExecutionDeniedError, ProviderError

PLUGIN_API_VERSION = "1.0.0"
_ENTRY_POINT_GROUP = "stonks_cli.providers"
_MANIFEST_HEADER = "Stonks-Cli-Provider-Manifest"
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


@dataclass(frozen=True)
class ProviderCapabilityRegistry:
    manifests: tuple[PluginManifest, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(manifest, PluginManifest) for manifest in self.manifests):
            raise ProviderError("capability registry contains an invalid manifest")
        if len({manifest.identifier for manifest in self.manifests}) != len(self.manifests):
            raise ProviderError("capability registry contains duplicate providers")
        for manifest in self.manifests:
            validate_manifest(manifest)
        object.__setattr__(
            self, "manifests", tuple(sorted(self.manifests, key=lambda item: item.identifier))
        )

    def providers_for(self, capability: Capability) -> tuple[str, ...]:
        if not isinstance(capability, Capability):
            raise ProviderError("provider capability is invalid")
        return tuple(
            manifest.identifier for manifest in self.manifests if capability in manifest.capabilities
        )

    def capabilities_for(self, identifier: str) -> frozenset[Capability]:
        for manifest in self.manifests:
            if manifest.identifier == identifier:
                return manifest.capabilities
        raise ProviderError("provider is not registered")


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


def provider_entry_points() -> tuple[metadata.EntryPoint, ...]:
    return tuple(sorted(metadata.entry_points(group=_ENTRY_POINT_GROUP), key=lambda entry: entry.name))


def discover_manifests() -> tuple[PluginManifest, ...]:
    manifests = tuple(_manifest_from_entry_point(entry) for entry in provider_entry_points())
    if len({manifest.identifier for manifest in manifests}) != len(manifests):
        raise ProviderError("duplicate plugin manifest identifier")
    return tuple(sorted(manifests, key=lambda manifest: manifest.identifier))


def _manifest_from_entry_point(entry: metadata.EntryPoint) -> PluginManifest:
    distribution = entry.dist
    if distribution is None:
        raise ProviderError(f"plugin distribution is unavailable:{entry.name}")
    try:
        raw = distribution.metadata[_MANIFEST_HEADER]
    except KeyError:
        raise ProviderError(f"plugin manifest metadata is missing:{entry.name}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProviderError(f"plugin manifest metadata is invalid:{entry.name}") from error
    if not isinstance(payload, dict):
        raise ProviderError(f"plugin manifest metadata is invalid:{entry.name}")
    identifier = payload.get("identifier")
    api_version = payload.get("api_version")
    capabilities = payload.get("capabilities")
    if (
        not isinstance(identifier, str)
        or not isinstance(api_version, str)
        or not isinstance(capabilities, list)
        or not all(isinstance(capability, str) for capability in capabilities)
    ):
        raise ProviderError(f"plugin manifest metadata is invalid:{entry.name}")
    try:
        manifest = PluginManifest(
            identifier, api_version, frozenset(Capability(capability) for capability in capabilities)
        )
    except (ProviderError, ValueError) as error:
        raise ProviderError(f"plugin manifest metadata is invalid:{entry.name}") from error
    if manifest.identifier != entry.name:
        raise ProviderError(f"plugin manifest identifier does not match entry point:{entry.name}")
    return manifest


def validate_provider_compatibility(provider: ProviderPlugin, expected: PluginManifest) -> None:
    manifest = getattr(provider, "manifest", None)
    if not isinstance(manifest, PluginManifest):
        raise ProviderError(f"plugin missing manifest:{expected.identifier}")
    validate_manifest(manifest)
    if manifest != expected:
        raise ProviderError(f"plugin manifest does not match static metadata:{expected.identifier}")


def discover() -> dict[str, ProviderPlugin]:
    expected = {
        manifest.identifier: manifest
        for manifest in ProviderCapabilityRegistry(discover_manifests()).manifests
    }
    providers: dict[str, ProviderPlugin] = {}
    for entry in provider_entry_points():
        provider = entry.load()
        manifest = expected[entry.name]
        validate_provider_compatibility(provider, manifest)
        providers[manifest.identifier] = provider
    return dict(sorted(providers.items()))
