from __future__ import annotations

import pytest

from stonks_cli.errors import ExecutionDeniedError, ProviderError
from stonks_cli.plugins import Capability, PluginManifest, validate_manifest


def test_read_only_manifest_is_valid() -> None:
    validate_manifest(PluginManifest("fixture", 1, frozenset({Capability.ACCOUNTS})))


def test_manifest_schema_canonicalizes_identifier_and_accepts_future_revision() -> None:
    manifest = PluginManifest(" Fixture-Provider ", 2, frozenset({Capability.ACCOUNTS}))
    assert manifest.identifier == "fixture-provider"
    assert manifest.api_version == 2


@pytest.mark.parametrize(
    ("identifier", "api_version", "capabilities", "error"),
    (
        ("bad provider", 1, frozenset({Capability.ACCOUNTS}), "identifier"),
        ("fixture", 0, frozenset({Capability.ACCOUNTS}), "API version"),
        ("fixture", 1, frozenset(), "capabilities"),
    ),
)
def test_manifest_schema_rejects_invalid_values(
    identifier: str, api_version: int, capabilities: frozenset[Capability], error: str
) -> None:
    with pytest.raises(ProviderError, match=error):
        PluginManifest(identifier, api_version, capabilities)


def test_manifest_rejects_non_capability_value() -> None:
    manifest = PluginManifest("unsafe", 1, frozenset({"execution"}))  # type: ignore[arg-type]
    with pytest.raises(ExecutionDeniedError):
        validate_manifest(manifest)
