# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    SolomonService,
    VerificationAssignmentRequest,
    VerificationRequest,
    VerificationReviewRequest,
)
from solomon.audit.journal import AuditJournal
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.errors import BadRequestError
from solomon.graph.models import EdgeType


def test_verification_lifecycle_assign_review_reaffirm_and_audit_pack(tmp_path: Path) -> None:
    service, item_id = _stale_service(tmp_path)

    requested = service.verification_queue()
    assert requested[0]["item"]["id"] == item_id
    assert requested[0]["latest_event"]["state"] == "verification_requested"

    service.assign_verification(
        item_id,
        VerificationAssignmentRequest(
            assigned_by="psl-a",
            reviewer_id="partner-a",
            role="partner",
            basis="Regulation R moved",
        ),
    )
    service.start_verification_review(
        item_id,
        VerificationReviewRequest(reviewer_id="partner-a", basis="reviewing updated authority"),
    )
    updated = service.record_verification(
        item_id,
        VerificationRequest(
            by="partner-a",
            outcome=VerificationOutcome.REAFFIRM,
            basis="updated authority does not change the firm position",
            source_ref="memo-2",
        ),
    )

    history = updated.metadata["verification_events"]
    assert [event["state"] for event in history] == [
        "verification_requested",
        "assigned",
        "in_review",
        "reaffirmed",
    ]
    assert history[1]["reviewer_id"] == "partner-a"
    assert history[-1]["basis"] == "updated authority does not change the firm position"
    assert service.audit.verify().ok is True
    assert "verification_lifecycle_event" in service.audit.path.read_text(encoding="utf-8")

    pack_dir = service.export_audit_pack(tmp_path / "pack")
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    history_path = pack_dir / manifest["verification_history_file"]
    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    assert history_payload[item_id][-1]["state"] == "reaffirmed"
    assert AuditJournal.verify_pack(pack_dir).ok is True
    history_path.write_text("{}", encoding="utf-8")
    assert AuditJournal.verify_pack(pack_dir).ok is False


def test_verification_completion_requires_basis(tmp_path: Path) -> None:
    service, item_id = _stale_service(tmp_path)

    with pytest.raises(BadRequestError, match="verification basis"):
        service.record_verification(
            item_id,
            VerificationRequest(by="partner-a", outcome=VerificationOutcome.REAFFIRM),
        )


def _stale_service(tmp_path: Path) -> tuple[SolomonService, str]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x depends on Regulation R section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="regulation-r-section-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.register_authority_change(
        "regulation-r-section-12",
        AuthorityChangeRequest(new_version="v2", changed_at="2026-01-01T00:00:00+00:00"),
    )
    return service, item.id
