# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import textwrap
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.contradiction import ContradictionSignal, contradictions_for_item
from solomon.currency.engine import evaluate_currency
from solomon.currency.models import CurrencyState, KnowledgeItem, _ensure_aware_utc, now_utc
from solomon.currency.verification import latest_verification_event
from solomon.graph.types import DependencyGraphProtocol
from solomon.store.types import KnowledgeEvent, KnowledgeStoreProtocol

ReportScopeKind = Literal["firm", "practice_area", "matter"]
MovementType = Literal["stale", "superseded", "retired", "contradictory"]

REPORT_EVENT_TYPES = {
    "knowledge_item_stale_flagged",
    "knowledge_item_contested",
    "knowledge_item_contradiction_flagged",
    "knowledge_item_superseded",
    "verification_lifecycle_completed",
}


class CurrencyReport(SolomonModel):
    matter_id: str | None
    client_id: str | None
    items: list[dict[str, Any]]


class CurrencyReportScope(SolomonModel):
    scope: ReportScopeKind = "firm"
    practice_area: str | None = None
    matter_id: str | None = None
    client_id: str | None = None


class CurrencyReportItem(SolomonModel):
    item_id: str
    kind: str
    movement_type: MovementType
    movement_at: datetime
    current_currency_state: str
    current_verification_status: str | None = None
    verified_state: str
    authority_id: str | None = None
    authority_changed_at: datetime | None = None
    reason: str
    source_ref: str
    matter_id: str | None = None
    client_id: str | None = None
    practice_area: str | None = None
    successor_id: str | None = None
    dependency_edges: list[dict[str, Any]] = Field(default_factory=list)
    dependent_items: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    latest_verification_event: dict[str, Any] | None = None

    @field_validator("movement_at", "authority_changed_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_aware_utc(value)


class CurrencyMovementReport(SolomonModel):
    schema_id: str = "solomon.currency_report.v1"
    generated_at: datetime = Field(default_factory=now_utc)
    period_start: datetime
    period_end: datetime
    scope: CurrencyReportScope
    items: list[CurrencyReportItem]
    totals: dict[str, int]
    report_sha256: str

    @field_validator("period_start", "period_end", "generated_at")
    @classmethod
    def normalize_period_datetime(cls, value: datetime) -> datetime:
        return _ensure_aware_utc(value)


def currency_report(
    *,
    store: KnowledgeStoreProtocol,
    graph: DependencyGraphProtocol,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> CurrencyReport:
    items = []
    for item in store.get_many(matter_id=matter_id, client_id=client_id):
        items.append(
            {
                "item_id": item.id,
                "kind": item.kind.value,
                "currency": evaluate_currency(item).model_dump(mode="json"),
                "dependencies": [edge.model_dump(mode="json") for edge in graph.get_dependencies(item.id)],
                "credence_tier": item.credence_tier.value,
                "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
            }
        )
    return CurrencyReport(matter_id=matter_id, client_id=client_id, items=items)


def currency_movement_report(
    *,
    store: KnowledgeStoreProtocol,
    graph: DependencyGraphProtocol,
    period_start: datetime,
    period_end: datetime,
    scope: ReportScopeKind = "firm",
    practice_area: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> CurrencyMovementReport:
    start = _ensure_aware_utc(period_start)
    end = _ensure_aware_utc(period_end)
    if end < start:
        raise ValueError("period_end must be on or after period_start")
    report_scope = CurrencyReportScope(
        scope=scope,
        practice_area=practice_area,
        matter_id=matter_id,
        client_id=client_id,
    )
    rows: list[CurrencyReportItem] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for event in store.list_events(since=start, until=end, event_types=REPORT_EVENT_TYPES):
        for row in _rows_for_event(event, store=store, graph=graph, scope=report_scope):
            key = (row.item_id, row.movement_type, row.movement_at.isoformat(), row.authority_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda row: (row.movement_at, row.item_id, row.movement_type, row.authority_id or ""))
    totals = {movement: 0 for movement in ["stale", "superseded", "retired", "contradictory"]}
    for row in rows:
        totals[row.movement_type] += 1
    payload = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "scope": report_scope.model_dump(mode="json"),
        "items": [row.model_dump(mode="json") for row in rows],
        "totals": totals,
    }
    return CurrencyMovementReport(
        period_start=start,
        period_end=end,
        scope=report_scope,
        items=rows,
        totals=totals,
        report_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest(),
    )


def render_currency_report_text(report: CurrencyMovementReport) -> str:
    lines = [
        "Solomon currency report",
        f"period: {report.period_start.isoformat()} to {report.period_end.isoformat()}",
        _scope_line(report.scope),
        _totals_line(report.totals),
        "",
    ]
    if not report.items:
        lines.append("No currency movements found for this scope and period.")
    for index, item in enumerate(report.items, start=1):
        lines.extend(
            [
                f"{index}. {item.movement_type.upper()} {item.item_id}",
                f"   source: {item.source_ref}",
                (
                    f"   current: {item.current_currency_state}; "
                    f"verification: {item.current_verification_status or 'none'}"
                ),
                f"   authority: {item.authority_id or 'n/a'}; moved: {_moved_at(item)}",
                f"   reason: {item.reason}",
                f"   dependents: {', '.join(row['item_id'] for row in item.dependent_items) or 'none'}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_currency_report_pdf(report: CurrencyMovementReport) -> bytes:
    lines = []
    for raw_line in render_currency_report_text(report).splitlines():
        wrapped = textwrap.wrap(_ascii(raw_line), width=92) or [""]
        lines.extend(wrapped)
    pages = [lines[index : index + 48] for index in range(0, len(lines), 48)] or [[]]
    return _pdf_from_pages(pages)


def _rows_for_event(
    event: KnowledgeEvent,
    *,
    store: KnowledgeStoreProtocol,
    graph: DependencyGraphProtocol,
    scope: CurrencyReportScope,
) -> list[CurrencyReportItem]:
    if event.event_type == "knowledge_item_superseded":
        predecessor = KnowledgeItem.model_validate(event.payload["predecessor"])
        current = _current_or_event_item(store, predecessor)
        if not _item_in_scope(current, scope):
            return []
        return [
            _row(
                current,
                graph=graph,
                movement_type="superseded",
                movement_at=event.occurred_at,
                reason="item was superseded",
            )
        ]
    item_payload = event.payload.get("item")
    if not isinstance(item_payload, dict):
        return []
    event_item = KnowledgeItem.model_validate(item_payload)
    current = _current_or_event_item(store, event_item)
    if not _item_in_scope(current, scope):
        return []
    if event.event_type == "knowledge_item_contradiction_flagged":
        return [
            _row(
                current,
                graph=graph,
                movement_type="contradictory",
                movement_at=_signal_time(signal),
                authority_id=signal.authority_id,
                authority_changed_at=_signal_time(signal),
                reason=signal.basis,
            )
            for signal in contradictions_for_item(event_item)
            if _between(_signal_time(signal), event.occurred_at, event.occurred_at)
        ] or [
            _row(
                current,
                graph=graph,
                movement_type="contradictory",
                movement_at=event.occurred_at,
                reason="contradiction flagged",
            )
        ]
    if event.event_type == "verification_lifecycle_completed":
        if event_item.currency_state is CurrencyState.RETIRED:
            return [
                _row(
                    current,
                    graph=graph,
                    movement_type="retired",
                    movement_at=event.occurred_at,
                    reason="item was retired",
                )
            ]
        if event_item.currency_state is CurrencyState.SUPERSEDED:
            return [
                _row(
                    current,
                    graph=graph,
                    movement_type="superseded",
                    movement_at=event.occurred_at,
                    reason="verification marked item superseded",
                )
            ]
        return []
    return _stale_rows(current, event_item=event_item, graph=graph, event_at=event.occurred_at)


def _stale_rows(
    current: KnowledgeItem,
    *,
    event_item: KnowledgeItem,
    graph: DependencyGraphProtocol,
    event_at: datetime,
) -> list[CurrencyReportItem]:
    reasons = [reason for reason in event_item.metadata.get("staleness_reasons", []) if isinstance(reason, dict)]
    event_time = _ensure_aware_utc(event_at)
    reasons = [reason for reason in reasons if _reason_time(reason) is None or _reason_time(reason) == event_time]
    if not reasons:
        return [
            _row(
                current,
                graph=graph,
                movement_type="stale",
                movement_at=event_at,
                reason="item was flagged stale",
            )
        ]
    return [
        _row(
            current,
            graph=graph,
            movement_type="stale",
            movement_at=_reason_time(reason) or event_at,
            authority_id=str(reason.get("dependency_id")) if reason.get("dependency_id") else None,
            authority_changed_at=_reason_time(reason),
            reason=str(reason.get("reason") or "dependency moved"),
        )
        for reason in reasons
    ]


def _row(
    item: KnowledgeItem,
    *,
    graph: DependencyGraphProtocol,
    movement_type: MovementType,
    movement_at: datetime,
    reason: str,
    authority_id: str | None = None,
    authority_changed_at: datetime | None = None,
) -> CurrencyReportItem:
    latest_event = latest_verification_event(item)
    dependents = []
    for edge in graph.get_dependents(item.id):
        dependents.append({"item_id": edge.source_id, "edge_id": edge.id, "edge_type": edge.edge_type.value})
    return CurrencyReportItem(
        item_id=item.id,
        kind=item.kind.value,
        movement_type=movement_type,
        movement_at=movement_at,
        current_currency_state=evaluate_currency(item).currency_state.value,
        current_verification_status=(
            str(item.metadata["verification_status"]) if item.metadata.get("verification_status") is not None else None
        ),
        verified_state=item.verified_state.value,
        authority_id=authority_id,
        authority_changed_at=authority_changed_at,
        reason=reason,
        source_ref=item.provenance.source_ref,
        matter_id=item.matter_id,
        client_id=item.client_id,
        practice_area=_practice_area(item),
        successor_id=item.successor_id,
        dependency_edges=[edge.model_dump(mode="json") for edge in graph.get_dependencies(item.id)],
        dependent_items=dependents,
        contradictions=[signal.model_dump(mode="json") for signal in contradictions_for_item(item)],
        latest_verification_event=latest_event.model_dump(mode="json") if latest_event else None,
    )


def _current_or_event_item(store: KnowledgeStoreProtocol, event_item: KnowledgeItem) -> KnowledgeItem:
    try:
        return store.get_item(event_item.id)
    except Exception:
        return event_item


def _item_in_scope(item: KnowledgeItem, scope: CurrencyReportScope) -> bool:
    if scope.client_id is not None and item.client_id != scope.client_id:
        return False
    if scope.scope == "matter":
        return scope.matter_id is not None and item.matter_id == scope.matter_id
    if scope.scope == "practice_area":
        return scope.practice_area is not None and _practice_area(item) == scope.practice_area
    if scope.matter_id is not None and item.matter_id != scope.matter_id:
        return False
    if scope.practice_area is not None and _practice_area(item) != scope.practice_area:
        return False
    return True


def _practice_area(item: KnowledgeItem) -> str | None:
    value = item.metadata.get("practice_area")
    return str(value) if value is not None else None


def _reason_time(reason: dict[str, Any]) -> datetime | None:
    value = reason.get("changed_at")
    if value is None:
        return None
    return _ensure_aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _signal_time(signal: ContradictionSignal) -> datetime:
    return _ensure_aware_utc(signal.detected_at)


def _between(value: datetime, start: datetime, end: datetime) -> bool:
    normalized = _ensure_aware_utc(value)
    return _ensure_aware_utc(start) <= normalized <= _ensure_aware_utc(end)


def _scope_line(scope: CurrencyReportScope) -> str:
    parts = [f"scope: {scope.scope}"]
    if scope.practice_area:
        parts.append(f"practice_area={scope.practice_area}")
    if scope.matter_id:
        parts.append(f"matter_id={scope.matter_id}")
    if scope.client_id:
        parts.append(f"client_id={scope.client_id}")
    return "; ".join(parts)


def _totals_line(totals: dict[str, int]) -> str:
    values = [f"{name}={count}" for name, count in sorted(totals.items()) if count]
    return "totals: " + (", ".join(values) if values else "none")


def _moved_at(item: CurrencyReportItem) -> str:
    moved_at = item.authority_changed_at or item.movement_at
    return moved_at.isoformat()


def _ascii(value: str) -> str:
    return value.encode("ascii", "replace").decode("ascii")


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_from_pages(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []
    page_refs: list[str] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_index, lines in enumerate(pages):
        page_number = 4 + page_index * 2
        content_number = page_number + 1
        page_refs.append(f"{page_number} 0 R")
        stream = _page_stream(lines)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>".encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(pages)} >>".encode("ascii")
    chunks = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    xref = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    chunks.extend(
        [
            *xref,
            b"trailer\n<< /Size ",
            str(len(objects) + 1).encode("ascii"),
            b" /Root 1 0 R >>\nstartxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(chunks)


def _page_stream(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 10 Tf", "50 760 Td", "13 TL"]
    for line in lines:
        commands.append(f"({_pdf_escape(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    return "\n".join(commands).encode("ascii")
