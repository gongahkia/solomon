from __future__ import annotations

import json

import pytest

from stonks_cli import plugins
from stonks_cli.errors import ExecutionDeniedError, ProviderError
from stonks_cli.plugins import (
    Capability,
    PluginManifest,
    ProviderCapabilityRegistry,
    compatible_api_version,
    discover,
    discover_manifests,
    provider_entry_points,
    validate_manifest,
    validate_provider_compatibility,
)


def test_read_only_manifest_is_valid() -> None:
    validate_manifest(PluginManifest("fixture", "1.0.0", frozenset({Capability.ACCOUNTS})))


def test_manifest_schema_canonicalizes_identifier_and_accepts_future_revision() -> None:
    manifest = PluginManifest(" Fixture-Provider ", "2.0.0", frozenset({Capability.ACCOUNTS}))
    assert manifest.identifier == "fixture-provider"
    assert manifest.api_version == "2.0.0"


@pytest.mark.parametrize(
    ("identifier", "api_version", "capabilities", "error"),
    (
        ("bad provider", "1.0.0", frozenset({Capability.ACCOUNTS}), "identifier"),
        ("fixture", "1.0", frozenset({Capability.ACCOUNTS}), "API version"),
        ("fixture", "1.0.0", frozenset(), "capabilities"),
    ),
)
def test_manifest_schema_rejects_invalid_values(
    identifier: str, api_version: str, capabilities: frozenset[Capability], error: str
) -> None:
    with pytest.raises(ProviderError, match=error):
        PluginManifest(identifier, api_version, capabilities)


def test_manifest_rejects_non_capability_value() -> None:
    manifest = PluginManifest("unsafe", "1.0.0", frozenset({"execution"}))  # type: ignore[arg-type]
    with pytest.raises(ExecutionDeniedError):
        validate_manifest(manifest)


def test_capability_registry_is_typed_and_deterministic() -> None:
    registry = ProviderCapabilityRegistry(
        (
            PluginManifest("prices", "1.0.0", frozenset({Capability.MARKET_DATA})),
            PluginManifest(
                "accounts", "1.0.0", frozenset({Capability.ACCOUNTS, Capability.POSITIONS})
            ),
        )
    )

    assert registry.providers_for(Capability.ACCOUNTS) == ("accounts",)
    assert registry.providers_for(Capability.MARKET_DATA) == ("prices",)
    assert registry.capabilities_for("accounts") == frozenset(
        {Capability.ACCOUNTS, Capability.POSITIONS}
    )


def test_capability_registry_rejects_duplicate_provider_identifiers() -> None:
    manifest = PluginManifest("fixture", "1.0.0", frozenset({Capability.ACCOUNTS}))
    with pytest.raises(ProviderError, match="duplicate"):
        ProviderCapabilityRegistry((manifest, manifest))


class _FixturePlugin:
    def __init__(self, identifier: str) -> None:
        self.manifest = PluginManifest(identifier, "1.0.0", frozenset({Capability.ACCOUNTS}))


class _FixtureEntryPoint:
    def __init__(self, name: str, provider: _FixturePlugin) -> None:
        self.name = name
        self.provider = provider
        self.dist = _FixtureDistribution(
            {
                "identifier": provider.manifest.identifier,
                "api_version": provider.manifest.api_version,
                "capabilities": [capability.value for capability in provider.manifest.capabilities],
            }
        )

    def load(self) -> _FixturePlugin:
        return self.provider


class _FixtureDistribution:
    def __init__(self, manifest: dict[str, object]) -> None:
        self.metadata = {"Stonks-Cli-Provider-Manifest": json.dumps(manifest)}


class _ManifestEntryPoint:
    def __init__(self, name: str, manifest: dict[str, object]) -> None:
        self.name = name
        self.dist = _FixtureDistribution(manifest)

    def load(self) -> None:
        raise AssertionError("manifest discovery must not import providers")


def test_entry_point_discovery_loads_providers_in_deterministic_order(monkeypatch) -> None:
    entries = (
        _FixtureEntryPoint("prices", _FixturePlugin("prices")),
        _FixtureEntryPoint("accounts", _FixturePlugin("accounts")),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    assert tuple(entry.name for entry in provider_entry_points()) == ("accounts", "prices")
    assert list(discover()) == ["accounts", "prices"]


def test_manifest_discovery_does_not_import_provider_entry_points(monkeypatch) -> None:
    entries = (
        _ManifestEntryPoint(
            "fixture",
            {
                "identifier": "fixture",
                "api_version": "1.0.0",
                "capabilities": ["accounts.read"],
            },
        ),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    assert discover_manifests() == (
        PluginManifest("fixture", "1.0.0", frozenset({Capability.ACCOUNTS})),
    )


def test_provider_compatibility_rejects_runtime_manifest_mismatch(monkeypatch) -> None:
    entry = _FixtureEntryPoint("fixture", _FixturePlugin("fixture"))
    entry.dist = _FixtureDistribution(
        {
            "identifier": "fixture",
            "api_version": "1.0.0",
            "capabilities": ["market_data.read"],
        }
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: (entry,))

    with pytest.raises(ProviderError, match="does not match"):
        discover()
    with pytest.raises(ProviderError, match="does not match"):
        validate_provider_compatibility(
            _FixturePlugin("fixture"),
            PluginManifest("fixture", "1.0.0", frozenset({Capability.MARKET_DATA})),
        )


@pytest.mark.parametrize("version", ("1.0.0", "1.0.99"))
def test_plugin_api_policy_accepts_compatible_patch_versions(version: str) -> None:
    assert compatible_api_version(version) is True


@pytest.mark.parametrize("version", ("1.1.0", "2.0.0"))
def test_plugin_api_policy_rejects_newer_minor_or_different_major(version: str) -> None:
    assert compatible_api_version(version) is False
    with pytest.raises(ProviderError, match="incompatible"):
        validate_manifest(PluginManifest("fixture", version, frozenset({Capability.ACCOUNTS})))
