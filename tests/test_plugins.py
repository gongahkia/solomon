from __future__ import annotations

import pytest

from stonks_cli.errors import ExecutionDeniedError
from stonks_cli.plugins import Capability, PluginManifest, validate_manifest


def test_read_only_manifest_is_valid() -> None:
    validate_manifest(PluginManifest("fixture", 1, frozenset({Capability.ACCOUNTS})))


def test_manifest_rejects_non_capability_value() -> None:
    manifest = PluginManifest("unsafe", 1, frozenset({"execution"}))  # type: ignore[arg-type]
    with pytest.raises(ExecutionDeniedError):
        validate_manifest(manifest)
