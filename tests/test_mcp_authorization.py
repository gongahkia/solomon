# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from solomon.api.auth import AuthRole
from solomon.api.service import IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.mcp.auth import (
    MCP_AUDIT_SCOPE,
    MCP_READ_SCOPE,
    MCP_WRITE_SCOPE,
    MCPAuthConfig,
    MCPPrincipal,
    current_mcp_call,
)
from solomon.mcp.rate_limit import TokenBucketConfig, TokenBucketRateLimiter
from solomon.mcp.server import MCPBearerAuthMiddleware
from solomon.mcp.tools.runtime import SolomonMCPRuntime


def _item(service: SolomonService, *, matter_id: str = "matter-a", client_id: str = "client-a") -> str:
    return service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="scoped MCP position",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id=matter_id,
            client_id=client_id,
        )
    ).id


def _principal(
    *,
    subject: str = "lawyer-a",
    role: AuthRole = "lawyer",
    scopes: frozenset[str] = frozenset({MCP_READ_SCOPE}),
    matter_ids: frozenset[str] = frozenset({"matter-a"}),
    client_ids: frozenset[str] = frozenset({"client-a"}),
) -> MCPPrincipal:
    return MCPPrincipal(
        subject=subject,
        role=role,
        scopes=scopes,
        matter_ids=matter_ids,
        client_ids=client_ids,
    )


def test_mcp_bound_identity_authorizes_scope_and_audits_actual_actor(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item_id = _item(service)
    runtime = SolomonMCPRuntime(service, principal=_principal())

    result = runtime.check_currency(
        knowledge_item_id=item_id,
        matter_id="matter-a",
        client_id="client-a",
        caller_id="spoofed-host-identity",
    )

    assert result["state"] == "live"
    entries = [
        json.loads(line)
        for line in (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    entry = next(entry for entry in reversed(entries) if entry["event_type"] == "mcp_call")
    assert entry["attribution"]["actor_id"] == "lawyer-a"
    assert entry["attribution"]["correlation_id"].startswith("mcp:")
    assert entry["payload"]["caller_id"] == "lawyer-a"
    assert entry["payload"]["metadata"]["identity"] == {
        "roles": ["lawyer"],
        "scopes": [MCP_READ_SCOPE],
    }
    assert service.audit.verify().ok is True


def test_mcp_forbids_missing_tool_scope_and_out_of_scope_item(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    allowed_item = _item(service)
    denied_item = _item(service, matter_id="matter-b", client_id="client-b")
    runtime = SolomonMCPRuntime(service, principal=_principal())

    missing_scope = runtime.ingest(
        text="unauthorized write",
        source_ref="memo-2",
        scope={"matter_id": "matter-a", "client_id": "client-a"},
        caller_id="spoofed-host-identity",
    )
    wrong_scope = runtime.check_currency(
        knowledge_item_id=denied_item,
        matter_id="matter-b",
        client_id="client-b",
        caller_id="spoofed-host-identity",
    )
    role_denied = SolomonMCPRuntime(
        service,
        principal=_principal(role="integration", scopes=frozenset({MCP_WRITE_SCOPE})),
    ).ingest(
        text="role denied write",
        source_ref="memo-3",
        scope={"matter_id": "matter-a", "client_id": "client-a"},
    )
    allowed = runtime.check_currency(
        knowledge_item_id=allowed_item,
        matter_id="matter-a",
        client_id="client-a",
    )

    assert missing_scope["error"]["code"] == "authorization_denied"
    assert wrong_scope["error"]["code"] == "authorization_denied"
    assert role_denied["error"]["code"] == "authorization_denied"
    assert allowed["state"] == "live"
    assert len(service.store.get_many()) == 2


def test_mcp_restricted_principal_cannot_request_global_exports(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item_id = _item(service)
    runtime = SolomonMCPRuntime(
        service,
        principal=_principal(scopes=frozenset({MCP_READ_SCOPE, MCP_AUDIT_SCOPE})),
    )

    audit_pack = runtime.audit_pack(
        knowledge_item_id=item_id,
        matter_id="matter-a",
        client_id="client-a",
    )
    report = runtime.currency_report(
        period_start="2026-01-01T00:00:00+00:00",
        period_end="2026-12-31T00:00:00+00:00",
        scope="firm",
        matter_id="matter-a",
        client_id="client-a",
    )

    assert audit_pack["error"]["code"] == "authorization_denied"
    assert report["error"]["code"] == "authorization_denied"


def test_mcp_rate_limit_uses_bound_principal_not_caller_argument(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item_id = _item(service)
    runtime = SolomonMCPRuntime(
        service,
        rate_limiter=TokenBucketRateLimiter(TokenBucketConfig(capacity=1, refill_per_second=0.0)),
        principal=_principal(),
    )

    first = runtime.check_currency(
        knowledge_item_id=item_id,
        matter_id="matter-a",
        client_id="client-a",
        caller_id="caller-a",
    )
    second = runtime.check_currency(
        knowledge_item_id=item_id,
        matter_id="matter-a",
        client_id="client-a",
        caller_id="caller-b",
    )

    assert first["state"] == "live"
    assert second["error"]["code"] == "rate_limited"
    assert second["error"]["details"]["caller_id"] == "lawyer-a"


def test_mcp_http_identity_resolver_requires_and_binds_bearer_identity() -> None:
    app = Starlette()
    credential = "host-" + "token"

    async def endpoint(_request: Request) -> JSONResponse:
        context = current_mcp_call()
        return JSONResponse({"subject": context.principal.subject if context and context.principal else None})

    app.add_route("/mcp", endpoint)
    app.add_middleware(
        MCPBearerAuthMiddleware,
        expected_token=None,
        auth=MCPAuthConfig(),
        metadata_path="/.well-known/oauth-protected-resource/mcp",
        identity_resolver=lambda token: _principal(subject="host-user") if token == credential else None,
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://mcp.example.test",
        ) as client:
            denied = await client.get("/mcp", headers={"authorization": "Bearer wrong"})
            accepted = await client.get("/mcp", headers={"authorization": f"Bearer {credential}"})
            return denied, accepted

    denied, accepted = asyncio.run(exercise())

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"subject": "host-user"}


def test_mcp_required_identity_denies_unbound_runtime_calls(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    runtime = SolomonMCPRuntime(service, require_identity=True)

    result = runtime.health(caller_id="untrusted")

    assert result["error"]["code"] == "authorization_denied"
