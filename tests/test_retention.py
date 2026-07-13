# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from solomon.api.app import create_app
from solomon.api.auth import AuthPrincipal, AuthRole, scopes_for_roles
from solomon.api.service import IngestRequest, SolomonService
from solomon.audit.journal import AuditJournal
from solomon.config import Settings
from solomon.currency.models import CurrencyState, KnowledgeKind, SourceKind
from solomon.errors import PolicyRefusalError


def _principal(role: AuthRole) -> AuthPrincipal:
    roles: frozenset[AuthRole] = frozenset({role})
    return AuthPrincipal(
        subject=f"{role}-1",
        role=role,
        tenant_id="tenant-a",
        scopes=scopes_for_roles(roles),
        roles=roles,
    )


def test_legal_hold_blocks_erasure_then_tombstones_current_content_with_audit(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="confidential legal hold content",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    lawyer = _principal("lawyer")
    integration = _principal("integration")

    with service.authorized_as(lawyer, "retention-hold"):
        hold = service.create_legal_hold(scope="matter", scope_id="matter-a", reason="litigation preservation")
    with service.authorized_as(integration, "retention-denied"):
        with pytest.raises(PolicyRefusalError, match="not authorized"):
            service.erase_retention_scope(
                scope="matter",
                scope_id="matter-a",
                subject_ref="Jane Doe",
                lawful_basis="erasure request",
            )
    with service.authorized_as(lawyer, "retention-held"):
        held = service.erase_retention_scope(
            scope="matter",
            scope_id="matter-a",
            subject_ref="Jane Doe",
            lawful_basis="erasure request",
        )

    assert held.state == "held"
    assert held.legal_hold_ids == [hold.hold_id]
    assert service.store.get_item(item.id).content == "confidential legal hold content"

    with service.authorized_as(lawyer, "retention-release"):
        service.release_legal_hold(hold.hold_id)
    with service.authorized_as(lawyer, "retention-erased"):
        erased = service.erase_retention_scope(
            scope="matter",
            scope_id="matter-a",
            subject_ref="Jane Doe",
            lawful_basis="erasure request",
        )

    current = service.store.get_item(item.id)
    assert erased.state == "erased"
    assert erased.affected_item_ids == [item.id]
    assert current.content == "[erased under retention policy]"
    assert current.currency_state is CurrencyState.RETIRED
    assert current.metadata["retention"]["state"] == "erased"
    assert "Jane Doe" not in service.retention_registry.path.read_text(encoding="utf-8")

    completed = [
        entry
        for entry in service.audit.list_entries(correlation_id="retention-erased", actor_id="lawyer-1")
        if entry.event_type in {"erasure_completed", "erasure_tombstone"}
    ]
    assert [entry.event_type for entry in completed] == ["erasure_completed", "erasure_tombstone"]
    assert all(entry.attribution and entry.attribution.actor_id == "lawyer-1" for entry in completed)
    assert all(entry.attribution and entry.attribution.correlation_id == "retention-erased" for entry in completed)
    assert "Jane Doe" not in service.audit.path.read_text(encoding="utf-8")
    assert service.audit.verify().ok is True
    blocked = [
        entry
        for entry in service.audit.list_entries(correlation_id="retention-held", actor_id="lawyer-1")
        if entry.event_type == "erasure_blocked_by_legal_hold"
    ]
    assert blocked[0].payload["decision"] == "denied"
    denied = [
        entry
        for entry in service.audit.list_entries(correlation_id="retention-denied", actor_id="integration-1")
        if entry.event_type == "service_authorization"
    ]
    assert denied[0].payload["decision"] == "denied"


def test_configured_retention_erases_due_items_only_after_holds_release(tmp_path: Path) -> None:
    service = SolomonService(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        retention_default_days=30,
    )
    old = datetime.now(timezone.utc) - timedelta(days=31)
    old_item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.NOTE,
            content="retention due content",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-due",
            matter_id="matter-due",
            ingested_at=old,
        )
    )
    recent_item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.NOTE,
            content="retention current content",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-current",
            matter_id="matter-current",
            ingested_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )
    lawyer = _principal("lawyer")

    with service.authorized_as(lawyer, "retention-policy-hold"):
        hold = service.create_legal_hold(scope="item", scope_id=old_item.id, reason="matter hold")
        first = service.apply_retention()
        service.release_legal_hold(hold.hold_id)
        second = service.apply_retention()

    assert [record.state for record in first] == ["held"]
    assert [record.state for record in second] == ["erased"]
    assert service.store.get_item(old_item.id).currency_state is CurrencyState.RETIRED
    assert service.store.get_item(recent_item.id).content == "retention current content"


def test_retention_admin_routes_require_admin_and_target_registered_server_tenant(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            sku="server",
            zero_egress_mode=False,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            server_api_key="admin-secret",
            server_auth_mode="legacy-api-key",
            server_auto_provision_tenants=False,
            retention_default_days=30,
        )
    )
    headers = {"x-api-key": "admin-secret", "x-correlation-id": "retention-admin"}

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            denied = await client.post(
                "/retention/legal-holds?tenant_id=tenant-a",
                json={"scope": "matter", "scope_id": "matter-a", "reason": "hold"},
            )
            created_tenant = await client.post("/tenants", headers=headers, json={"tenant_id": "tenant-a"})
            missing_tenant = await client.post(
                "/retention/legal-holds",
                headers=headers,
                json={"scope": "matter", "scope_id": "matter-a", "reason": "hold"},
            )
            created_hold = await client.post(
                "/retention/legal-holds?tenant_id=tenant-a",
                headers=headers,
                json={"scope": "matter", "scope_id": "matter-a", "reason": "hold"},
            )
            return denied, created_tenant, missing_tenant, created_hold

    denied, created_tenant, missing_tenant, created_hold = asyncio.run(exercise())

    assert denied.status_code == 401
    assert created_tenant.status_code == 201
    assert missing_tenant.status_code == 400
    assert created_hold.status_code == 201
    journal = AuditJournal(tmp_path / "journal" / "tenants" / "tenant-a" / "journal.jsonl")
    entries = journal.list_entries(correlation_id="retention-admin", actor_id="server-admin")
    assert entries[-1].event_type == "legal_hold_created"
    assert entries[-1].payload["decision"] == "allowed"
