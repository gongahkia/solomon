# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    SolomonService,
    VerificationRequest,
)
from solomon.audit.journal import AuditJournal
from solomon.currency.contradiction import ConclusionPolarity
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.currency.report import render_currency_report_pdf, render_currency_report_text
from solomon.graph.models import EdgeType


def _dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_currency_movement_report_covers_period_events_and_exports_pack(tmp_path: Path) -> None:
    service, ids = _report_service(tmp_path)

    report = service.currency_report(
        period_start=_dt(2026, 1, 1),
        period_end=_dt(2026, 12, 31),
        scope="matter",
        matter_id="matter-a",
        client_id="client-a",
    )

    movements = {(row.item_id, row.movement_type) for row in report.items}
    assert (ids["stale"], "stale") in movements
    assert (ids["superseded"], "superseded") in movements
    assert (ids["retired"], "retired") in movements
    assert (ids["allow"], "contradictory") in movements
    stale = next(row for row in report.items if row.item_id == ids["stale"])
    assert stale.authority_id == "reg-r-12"
    assert stale.authority_changed_at == _dt(2026, 1, 5)
    assert stale.current_verification_status == "verification_requested"
    assert report.totals["stale"] == 1
    assert report.totals["superseded"] == 1
    assert report.totals["retired"] == 1
    assert report.totals["contradictory"] == 2
    assert ids["stale"] in render_currency_report_text(report)
    assert render_currency_report_pdf(report).startswith(b"%PDF-1.4")

    pack_dir = service.export_currency_report_pack(tmp_path / "pack", report)
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["currency_report_file"] == "currency-report.json"
    assert manifest["currency_report_pdf_file"] == "currency-report.pdf"
    assert AuditJournal.verify_pack(pack_dir).ok is True


def _report_service(tmp_path: Path) -> tuple[SolomonService, dict[str, str]]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    ids: dict[str, str] = {}
    stale = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Structure X relies on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-stale",
            matter_id="matter-a",
            client_id="client-a",
            ingested_at=_dt(2025, 1, 1),
            valid_from=_dt(2025, 1, 1),
        )
    )
    ids["stale"] = stale.id
    service.add_dependency(
        DependencyRequest(
            source_id=stale.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="2026", changed_at="2026-01-05T00:00:00+00:00"),
    )
    successor = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Updated Structure Y position.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-successor",
            matter_id="matter-a",
            client_id="client-a",
            ingested_at=_dt(2026, 2, 1),
            valid_from=_dt(2026, 2, 1),
        )
    )
    ids["successor"] = successor.id
    superseded = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Old Structure Y position.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-old",
            matter_id="matter-a",
            client_id="client-a",
            ingested_at=_dt(2025, 2, 1),
            valid_from=_dt(2025, 2, 1),
        )
    )
    ids["superseded"] = superseded.id
    service.record_verification(
        superseded.id,
        VerificationRequest(
            by="partner-a",
            outcome=VerificationOutcome.SUPERSEDE,
            successor_id=successor.id,
            basis="new memo replaces old position",
            recorded_at=_dt(2026, 2, 2),
        ),
    )
    retired = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Retired Structure Z position.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-retired",
            matter_id="matter-a",
            client_id="client-a",
            ingested_at=_dt(2025, 3, 1),
            valid_from=_dt(2025, 3, 1),
        )
    )
    ids["retired"] = retired.id
    service.record_verification(
        retired.id,
        VerificationRequest(
            by="partner-a",
            outcome=VerificationOutcome.RETIRE,
            basis="position no longer used",
            recorded_at=_dt(2026, 3, 1),
        ),
    )
    allow = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Structure Q is allowed under Regulation Q.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-allow",
            matter_id="matter-a",
            client_id="client-a",
            conclusion="allowed",
            conclusion_polarity=ConclusionPolarity.AFFIRMATIVE,
        )
    )
    ids["allow"] = allow.id
    deny = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Structure Q is not allowed under Regulation Q.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-deny",
            matter_id="matter-a",
            client_id="client-a",
            conclusion="not allowed",
            conclusion_polarity=ConclusionPolarity.NEGATIVE,
        )
    )
    ids["deny"] = deny.id
    service.add_dependency(
        DependencyRequest(
            source_id=allow.id,
            target_id="reg-q",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=deny.id,
            target_id="reg-q",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    return service, ids
