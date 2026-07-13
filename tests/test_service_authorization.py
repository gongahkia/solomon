# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.api.auth import AuthPrincipal, AuthRole, scopes_for_roles
from solomon.api.service import ContestRequest, DocumentSourceRequest, IngestRequest, RecallRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.errors import PolicyRefusalError
from solomon.sources.models import DocumentSourceKind


def _principal(role: AuthRole) -> AuthPrincipal:
    roles: frozenset[AuthRole] = frozenset({role})
    return AuthPrincipal(
        subject=f"{role}-1",
        role=role,
        tenant_id="tenant-a",
        scopes=scopes_for_roles(roles),
        roles=roles,
    )


def test_service_layer_enforces_curation_and_review_roles_with_audit(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="service authorization position",
            source_kind=SourceKind.PARTNER,
            source_ref="memo",
        )
    )

    with service.authorized_as(_principal("curator"), "curator-source"):
        source = service.register_document_source(
            DocumentSourceRequest(name="knowledge", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
        )
    with service.authorized_as(_principal("reviewer"), "reviewer-source"):
        with pytest.raises(PolicyRefusalError, match="not authorized"):
            service.register_document_source(
                DocumentSourceRequest(name="denied", kind=DocumentSourceKind.FILESYSTEM, root_ref="/knowledge")
            )
    with service.authorized_as(_principal("curator"), "curator-contest"):
        with pytest.raises(PolicyRefusalError, match="not authorized"):
            service.contest(item.id, ContestRequest(lawyer_id="curator-1", reason="needs review"))
    with service.authorized_as(_principal("lawyer"), "lawyer-contest"):
        result = service.contest(item.id, ContestRequest(lawyer_id="lawyer-1", reason="needs review"))

    assert source.name == "knowledge"
    assert result.item.id == item.id
    entries = {
        entry.attribution.correlation_id: entry
        for entry in service.audit.list_entries()
        if entry.event_type == "service_authorization" and entry.attribution is not None
    }
    assert entries["curator-source"].payload == {
        "operation": "register_document_source",
        "access": "curate",
        "decision": "allowed",
        "roles": ["curator"],
    }
    assert entries["reviewer-source"].payload["decision"] == "denied"
    assert entries["reviewer-source"].attribution is not None
    assert entries["reviewer-source"].attribution.actor_id == "reviewer-1"
    assert entries["curator-contest"].payload["access"] == "review"
    assert entries["curator-contest"].payload["decision"] == "denied"
    assert entries["lawyer-contest"].payload["decision"] == "allowed"


def test_service_layer_allows_content_reads_only_for_read_scoped_principals(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    with service.authorized_as(_principal("integration"), "integration-read"):
        assert service.recall(RecallRequest(query="unused")) == []
    with service.authorized_as(
        AuthPrincipal(subject="no-read", role="tenant", tenant_id="tenant-a", scopes=frozenset()),
        "no-read",
    ):
        with pytest.raises(PolicyRefusalError, match="not authorized"):
            service.recall(RecallRequest(query="unused"))

    entries = {
        entry.attribution.correlation_id: entry
        for entry in service.audit.list_entries()
        if entry.event_type == "service_authorization" and entry.attribution is not None
    }
    assert entries["integration-read"].payload["decision"] == "allowed"
    assert entries["no-read"].payload["decision"] == "denied"
