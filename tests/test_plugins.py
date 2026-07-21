from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import invalidate_caches
from pathlib import Path

import pytest

from stonks_cli import plugins
from stonks_cli.errors import ExecutionDeniedError, ProviderError
from stonks_cli.market_data import DailyPrice
from stonks_cli.moomoo import MoomooReadOnlyProvider
from stonks_cli.plugins import (
    Capability,
    CorporateActionProvider,
    MarketDataProvider,
    PluginLoadDiagnostic,
    PluginManifest,
    ProviderCapabilityRegistry,
    ReadOnlyAccountProvider,
    TransactionSourceProvider,
    builtin_provider_manifests,
    compatible_api_version,
    discover,
    discover_manifests,
    discover_with_diagnostics,
    provider_entry_points,
    validate_manifest,
    validate_provider_compatibility,
    validate_provider_configuration,
    validate_provider_contract,
)
from stonks_cli.types import Account, Currency, Instrument


def test_read_only_manifest_is_valid() -> None:
    validate_manifest(PluginManifest("fixture", "1.0.0", frozenset({Capability.ACCOUNTS})))


def test_builtin_providers_are_registered_through_the_plugin_api() -> None:
    assert builtin_provider_manifests() == (MoomooReadOnlyProvider.manifest,)


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


@pytest.mark.parametrize(
    "capability",
    (
        "execution",
        "orders.cancel",
        "orders.modify",
        "orders.place",
        "orders.read",
        "orders.write",
        "trade.unlock",
    ),
)
def test_manifest_rejects_execution_capability(capability: str) -> None:
    manifest = PluginManifest("unsafe", "1.0.0", frozenset({capability}))  # type: ignore[arg-type]
    with pytest.raises(ExecutionDeniedError):
        validate_manifest(manifest)


def test_manifest_rejects_unknown_capability() -> None:
    manifest = PluginManifest("unknown", "1.0.0", frozenset({"unknown.read"}))  # type: ignore[arg-type]
    with pytest.raises(ProviderError, match="capability"):
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

    def accounts(self) -> tuple[Account, ...]:
        return (Account(self.manifest.identifier, "1"),)


class _AccountFixturePlugin(_FixturePlugin):
    def accounts(self) -> tuple[Account, ...]:
        return (Account("fixture", "1"),)


class _TransactionFixturePlugin(_FixturePlugin):
    def transaction_records(self, account: Account, start: datetime, end: datetime):
        return ({"account": account.key, "start": start.isoformat(), "end": end.isoformat()},)


class _CorporateActionFixturePlugin(_FixturePlugin):
    def corporate_actions(self, account: Account, start: datetime, end: datetime):
        return ({"account": account.key, "start": start.isoformat(), "end": end.isoformat()},)


class _MarketDataFixturePlugin(_FixturePlugin):
    def daily_prices(self, instruments: tuple[Instrument, ...], start: date, end: date):
        return tuple(DailyPrice(item, start, Decimal("100"), "a" * 64) for item in instruments)


def test_read_only_account_provider_protocol_requires_account_reader() -> None:
    provider = _AccountFixturePlugin("fixture")
    assert isinstance(provider, ReadOnlyAccountProvider)
    assert provider.accounts() == (Account("fixture", "1"),)


def test_transaction_source_provider_protocol_requires_bounded_record_reader() -> None:
    provider = _TransactionFixturePlugin("fixture")
    account = Account("fixture", "1")
    assert isinstance(provider, TransactionSourceProvider)
    assert provider.transaction_records(
        account, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    )[0]["account"] == "fixture:1"


def test_corporate_action_provider_protocol_requires_bounded_record_reader() -> None:
    provider = _CorporateActionFixturePlugin("fixture")
    account = Account("fixture", "1")
    assert isinstance(provider, CorporateActionProvider)
    assert provider.corporate_actions(
        account, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    )[0]["account"] == "fixture:1"


def test_market_data_provider_protocol_requires_daily_price_reader() -> None:
    provider = _MarketDataFixturePlugin("fixture")
    instrument = Instrument("SPY", "US", Currency.USD)
    assert isinstance(provider, MarketDataProvider)
    assert provider.daily_prices((instrument,), date(2026, 1, 1), date(2026, 1, 2))[0].close == Decimal("100")


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


class _FailingEntryPoint(_FixtureEntryPoint):
    def load(self) -> _FixturePlugin:
        raise RuntimeError("fixture load failed")


def test_entry_point_discovery_loads_providers_in_deterministic_order(monkeypatch) -> None:
    entries = (
        _FixtureEntryPoint("prices", _FixturePlugin("prices")),
        _FixtureEntryPoint("accounts", _FixturePlugin("accounts")),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    assert tuple(entry.name for entry in provider_entry_points()) == ("accounts", "prices")
    assert list(discover()) == ["accounts", "prices"]


def test_fixture_provider_package_discovers_as_read_only_plugin(monkeypatch) -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "fixture_provider"
    monkeypatch.syspath_prepend(str(fixture_root))
    invalidate_caches()

    discovery = discover_with_diagnostics()

    assert discovery.diagnostics == ()
    provider = dict(discovery.providers)["fixture"]
    assert isinstance(provider, ReadOnlyAccountProvider)
    assert isinstance(provider, TransactionSourceProvider)
    assert isinstance(provider, CorporateActionProvider)
    assert isinstance(provider, MarketDataProvider)
    assert validate_provider_contract(provider) == provider.manifest
    assert provider.accounts() == (Account("fixture", "account-1"),)


def test_provider_contract_rejects_missing_declared_capability_method() -> None:
    class IncompleteProvider:
        manifest = PluginManifest("incomplete", "1.0.0", frozenset({Capability.ACCOUNTS}))

    with pytest.raises(ProviderError, match="capability contract:accounts.read"):
        validate_provider_contract(IncompleteProvider())


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


def test_provider_configuration_accepts_static_external_provider_without_import(monkeypatch) -> None:
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

    assert validate_provider_configuration(("fixture",)) == ("fixture",)


def test_manifest_discovery_rejects_execution_capability_without_import(monkeypatch) -> None:
    entries = (
        _ManifestEntryPoint(
            "unsafe",
            {
                "identifier": "unsafe",
                "api_version": "1.0.0",
                "capabilities": ["orders.place"],
            },
        ),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    with pytest.raises(ExecutionDeniedError):
        discover_manifests()


def test_discovery_isolates_manifest_errors_without_import(monkeypatch) -> None:
    entries = (
        _FixtureEntryPoint("accounts", _FixturePlugin("accounts")),
        _ManifestEntryPoint("invalid", {"identifier": "invalid"}),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    discovery = discover_with_diagnostics()

    assert tuple(identifier for identifier, _ in discovery.providers) == ("accounts",)
    assert discovery.diagnostics == (
        PluginLoadDiagnostic("invalid", "ProviderError: plugin manifest metadata is invalid:invalid"),
    )


def test_discovery_isolates_load_errors_and_reports_diagnostics(monkeypatch) -> None:
    entries = (
        _FailingEntryPoint("broken", _FixturePlugin("broken")),
        _FixtureEntryPoint("accounts", _FixturePlugin("accounts")),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    discovery = discover_with_diagnostics()

    assert tuple(identifier for identifier, _ in discovery.providers) == ("accounts",)
    assert discovery.diagnostics == (
        PluginLoadDiagnostic("broken", "RuntimeError: fixture load failed"),
    )
    assert list(discover()) == ["accounts"]


def test_discovery_reports_duplicate_provider_diagnostics(monkeypatch) -> None:
    entries = (
        _FixtureEntryPoint("fixture", _FixturePlugin("fixture")),
        _FixtureEntryPoint("fixture", _FixturePlugin("fixture")),
    )
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda *, group: entries)

    discovery = discover_with_diagnostics()

    assert discovery.providers == ()
    assert discovery.diagnostics == (
        PluginLoadDiagnostic("fixture", "ProviderError: duplicate provider:fixture"),
        PluginLoadDiagnostic("fixture", "ProviderError: duplicate provider:fixture"),
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

    discovery = discover_with_diagnostics()
    assert discovery.providers == ()
    assert discovery.diagnostics == (
        PluginLoadDiagnostic(
            "fixture", "ProviderError: plugin manifest does not match static metadata:fixture"
        ),
    )
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
