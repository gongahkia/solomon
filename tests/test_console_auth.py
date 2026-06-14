# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import anyio
import httpx

from solomon.config import Settings
from solomon.console.app import create_console_app


def test_console_allows_requests_without_configured_token(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(settings=settings))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/console/verification")

    response = anyio.run(call)

    assert response.status_code == 200


def test_console_requires_configured_bearer_token(tmp_path: Path) -> None:
    configured_value = "dev-secret"
    settings = Settings(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        console_bearer_token=configured_value,
    )

    async def call() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=create_console_app(settings=settings))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            denied = await client.get("/console/verification")
            wrong = await client.get("/console/verification", headers={"Authorization": "Bearer wrong"})
            allowed = await client.get("/console/verification", headers={"Authorization": f"Bearer {configured_value}"})
            return denied, wrong, allowed

    denied, wrong, allowed = anyio.run(call)

    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert allowed.status_code == 200


def test_console_static_assets_remain_public_with_token(tmp_path: Path) -> None:
    configured_value = "dev-secret"
    settings = Settings(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        console_bearer_token=configured_value,
    )

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_console_app(settings=settings))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/console/static/console.css")

    response = anyio.run(call)

    assert response.status_code == 200
    assert ".workspace" in response.text
