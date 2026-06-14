# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from solomon.api.app import create_app
from solomon.boundary.solomon import probe_boundary_client
from solomon.config import Settings


def _route_endpoint(app_routes: list[object], path: str) -> Callable[[], Any]:
    for route in app_routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


def test_app_health_and_diagnostics_do_not_expose_secrets(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal", boundary_api_key="secret")
    app = create_app(settings)

    health = _route_endpoint(list(app.routes), "/health")
    diagnostics = _route_endpoint(list(app.routes), "/diagnostics")

    assert health().status == "ok"
    payload = diagnostics().model_dump()
    assert payload["settings"]["boundary_api_key_configured"] is True
    assert "secret" not in str(payload)


def test_boundary_client_probe_uses_local_engine() -> None:
    status = probe_boundary_client()

    assert status.importable is True
    assert status.engine_path == "src/solomon/boundary/engine"
    assert status.client_path == "src/solomon/boundary/engine/client.py"
