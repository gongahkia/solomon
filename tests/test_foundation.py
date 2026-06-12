# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from solomon.api.app import create_app
from solomon.boundary.kaypoh import probe_kaypoh_client
from solomon.config import Settings


def _route_endpoint(app_routes: list[object], path: str) -> Callable[[], Any]:
    for route in app_routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


def test_app_health_and_diagnostics_do_not_expose_secrets(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal", kaypoh_api_key="secret")
    app = create_app(settings)

    health = _route_endpoint(list(app.routes), "/health")
    diagnostics = _route_endpoint(list(app.routes), "/diagnostics")

    assert health().status == "ok"
    payload = diagnostics().model_dump()
    assert payload["settings"]["kaypoh_api_key_configured"] is True
    assert "secret" not in str(payload)


def test_kaypoh_client_probe_uses_vendored_engine_without_sibling_path() -> None:
    status = probe_kaypoh_client()

    assert status.importable is True
    assert status.repo_path == "vendored"
    assert status.client_path == "src/solomon/boundary/engine/client.py"
