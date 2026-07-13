# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import anyio
import httpx

from solomon.api.oidc import OIDCIdentity, OIDCValidationError
from solomon.config import Settings
from solomon.console.app import create_console_app


def test_console_allows_local_development_identity_without_configured_token(tmp_path: Path) -> None:
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
        console_role="reviewer",
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


def test_console_enforces_screen_roles_and_audits_decisions(tmp_path: Path) -> None:
    configured_value = "reviewer-secret"
    settings = Settings(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        console_bearer_token=configured_value,
        console_role="reviewer",
        console_user_id="reviewer-1",
    )
    app = create_console_app(settings=settings)

    async def call() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {configured_value}", "x-correlation-id": "console-role"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            allowed = await client.get("/console/verification", headers=headers)
            denied = await client.get("/console/sources", headers=headers)
            return allowed, denied

    allowed, denied = anyio.run(call)

    assert allowed.status_code == 200
    assert denied.status_code == 403
    entries = [
        entry
        for entry in app.state.service.audit.list_entries(correlation_id="console-role", actor_id="reviewer-1")
        if entry.event_type == "console_authorization"
    ]
    assert [entry.payload["decision"] for entry in entries] == ["allowed", "denied"]


def test_console_uses_oidc_identity_in_server_mode(tmp_path: Path) -> None:
    configured_token = "oidc" + "-token"
    settings = Settings(
        sku="server",
        zero_egress_mode=False,
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        oidc_issuer="https://issuer.example",
        oidc_audience="solomon-console",
        oidc_role_mappings={"firm-reviewer": "reviewer"},
    )
    app = create_console_app(settings=settings)

    class Validator:
        def validate(self, token: str) -> OIDCIdentity:
            if token != configured_token:
                raise OIDCValidationError("invalid")
            return OIDCIdentity(
                subject="oidc-reviewer",
                issuer="https://issuer.example",
                audience=("solomon-console",),
                claims={"roles": ["firm-reviewer"]},
            )

    app.state.oidc_validator = Validator()

    async def call() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {configured_token}", "x-correlation-id": "console-oidc"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing = await client.get("/console/verification")
            allowed = await client.get("/console/verification", headers=headers)
            denied = await client.get("/console/sources", headers=headers)
            return missing, allowed, denied

    missing, allowed, denied = anyio.run(call)

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert denied.status_code == 403
