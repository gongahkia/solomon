# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from solomon.config import (
    Settings,
    boundary_policy_from_settings,
    local_settings,
    server_settings,
    settings_with_jurisdiction,
)


def test_local_sku_is_offline_default() -> None:
    settings = local_settings()

    assert settings.sku == "local"
    assert settings.allow_remote_egress is False
    assert settings.zero_egress_mode is True
    assert settings.boundary_base_url == "in-process://solomon-boundary-engine"


def test_local_sku_rejects_remote_egress() -> None:
    with pytest.raises(ValueError, match="local cannot enable remote egress"):
        Settings(sku="local", allow_remote_egress=True, zero_egress_mode=False)


def test_server_sku_requires_explicit_remote_model_for_egress() -> None:
    with pytest.raises(ValueError, match="requires SOLOMON_REMOTE_MODEL_URL"):
        server_settings(allow_remote_egress=True)

    settings = server_settings(allow_remote_egress=True, remote_model_url="https://zdr.example.test/v1")
    assert settings.sku == "server"
    assert settings.allow_remote_egress is True


def test_server_sku_requires_oidc_or_legacy_api_key() -> None:
    with pytest.raises(ValueError, match="OIDC server mode requires"):
        Settings(sku="server", zero_egress_mode=False)


def test_jurisdiction_profile_normalizes_and_sets_both_boundary_defaults() -> None:
    settings = Settings(jurisdiction="uk")

    policy = boundary_policy_from_settings(settings)

    assert settings.jurisdiction == "UK"
    assert policy.default_source_jurisdiction == "UK"
    assert policy.default_destination_jurisdiction == "UK"
    assert settings.public_diagnostics()["jurisdiction"] == "UK"
    assert settings_with_jurisdiction(settings, "eu").jurisdiction == "EU"


def test_jurisdiction_profile_rejects_unsupported_code() -> None:
    with pytest.raises(ValueError, match="jurisdiction must be one of"):
        Settings(jurisdiction="ID")
