# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from solomon.config import Settings, local_settings, server_settings


def test_local_sku_is_offline_default() -> None:
    settings = local_settings()

    assert settings.sku == "local"
    assert settings.allow_remote_egress is False
    assert settings.zero_egress_mode is True
    assert settings.kaypoh_base_url == "in-process://solomon-boundary-engine"


def test_local_sku_rejects_remote_egress() -> None:
    with pytest.raises(ValueError, match="local cannot enable remote egress"):
        Settings(sku="local", allow_remote_egress=True, zero_egress_mode=False)


def test_server_sku_requires_explicit_remote_model_for_egress() -> None:
    with pytest.raises(ValueError, match="requires SOLOMON_REMOTE_MODEL_URL"):
        server_settings(allow_remote_egress=True)

    settings = server_settings(allow_remote_egress=True, remote_model_url="https://zdr.example.test/v1")
    assert settings.sku == "server"
    assert settings.allow_remote_egress is True


def test_server_sku_requires_admin_api_key() -> None:
    with pytest.raises(ValueError, match="requires SOLOMON_SERVER_API_KEY"):
        Settings(sku="server", zero_egress_mode=False)
