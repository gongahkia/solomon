# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from enum import Enum

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.models import _ensure_aware_utc, now_utc


class ConsistencyScope(SolomonModel):
    """An explicit, exact knowledge scope; broad scans are intentionally unsupported."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=120)
    matter_id: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=500)

    @property
    def key(self) -> str:
        return "|".join((self.tenant_id or "", self.matter_id, self.client_id))


class ConsistencyFindingCode(str, Enum):
    CONFIRMED_ASSERTION_MISSING_EDGE = "confirmed_assertion_missing_edge"
    EDGE_INVALID_PROVENANCE = "edge_invalid_provenance"
    DUPLICATE_ASSERTION_EDGE = "duplicate_assertion_edge"
    OPERATION_STUCK = "operation_stuck"
    COMPLETED_PROJECTION_MISSING = "completed_projection_missing"
    UNKNOWN_OPERATION_PROJECTION = "unknown_operation_projection"
    CURRENCY_PROJECTION_STALE = "currency_projection_stale"
    SCOPE_MISMATCH = "scope_mismatch"
    SOURCE_VERSION_UNRECONSTRUCTIBLE = "source_version_unreconstructible"
    AUDIT_REFERENCE_MISSING = "audit_reference_missing"
    SOURCE_REVISION_OPERATION_MISSING = "source_revision_operation_missing"


class ConsistencyFinding(SolomonModel):
    code: ConsistencyFindingCode
    resource_type: str = Field(min_length=1, max_length=120)
    resource_id: str = Field(min_length=1, max_length=500)
    related_ids: list[str] = Field(default_factory=list)
    repairable: bool = False
    detail: str = Field(min_length=1, max_length=500)

    @property
    def key(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.code.value, self.resource_id, tuple(sorted(self.related_ids)))


class ConsistencyReport(SolomonModel):
    schema_id: str = "solomon.consistency_report.v1"
    scope: ConsistencyScope
    inspected_at: datetime = Field(default_factory=now_utc)
    findings: list[ConsistencyFinding] = Field(default_factory=list)
    state_fingerprint: str
    fingerprint: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_id": self.schema_id,
            "scope": self.scope.model_dump(mode="json"),
            "state_fingerprint": self.state_fingerprint,
            "findings": [
                finding.model_dump(mode="json") for finding in sorted(self.findings, key=lambda item: item.key)
            ],
        }

    @classmethod
    def create(
        cls,
        *,
        scope: ConsistencyScope,
        findings: list[ConsistencyFinding],
        observed_state: dict[str, object],
    ) -> ConsistencyReport:
        ordered = sorted(findings, key=lambda item: item.key)
        state_fingerprint = canonical_fingerprint(observed_state)
        payload = {
            "schema_id": "solomon.consistency_report.v1",
            "scope": scope.model_dump(mode="json"),
            "state_fingerprint": state_fingerprint,
            "findings": [finding.model_dump(mode="json") for finding in ordered],
        }
        return cls(
            scope=scope,
            findings=ordered,
            state_fingerprint=state_fingerprint,
            fingerprint=canonical_fingerprint(payload),
        )

    @staticmethod
    def _normalize_inspected_at(value: datetime) -> datetime:
        return _ensure_aware_utc(value)


class RepairAction(SolomonModel):
    action: str = Field(pattern=r"^[a-z_]+$", max_length=120)
    finding_code: ConsistencyFindingCode
    assertion_id: str | None = Field(default=None, min_length=1, max_length=500)
    previous_document_id: str | None = Field(default=None, min_length=1, max_length=500)
    replacement_document_id: str | None = Field(default=None, min_length=1, max_length=500)

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class RepairPlan(SolomonModel):
    schema_id: str = "solomon.consistency_repair_plan.v1"
    scope: ConsistencyScope
    report_fingerprint: str = Field(min_length=64, max_length=64)
    actions: list[RepairAction] = Field(default_factory=list)
    fingerprint: str = Field(min_length=64, max_length=64)

    @classmethod
    def create(
        cls,
        *,
        scope: ConsistencyScope,
        report_fingerprint: str,
        actions: list[RepairAction],
    ) -> RepairPlan:
        ordered = sorted(
            actions,
            key=lambda item: (
                item.action,
                item.assertion_id or "",
                item.previous_document_id or "",
                item.replacement_document_id or "",
            ),
        )
        payload = {
            "schema_id": "solomon.consistency_repair_plan.v1",
            "scope": scope.model_dump(mode="json"),
            "report_fingerprint": report_fingerprint,
            "actions": [action.canonical_payload() for action in ordered],
        }
        return cls(
            scope=scope,
            report_fingerprint=report_fingerprint,
            actions=ordered,
            fingerprint=canonical_fingerprint(payload),
        )

    def valid_fingerprint(self) -> bool:
        payload = {
            "schema_id": self.schema_id,
            "scope": self.scope.model_dump(mode="json"),
            "report_fingerprint": self.report_fingerprint,
            "actions": [action.canonical_payload() for action in self.actions],
        }
        return self.fingerprint == canonical_fingerprint(payload)


class RepairResult(SolomonModel):
    schema_id: str = "solomon.consistency_repair_result.v1"
    plan_fingerprint: str
    applied: bool
    idempotent: bool = False
    actions_applied: list[RepairAction] = Field(default_factory=list)
    refusal: str | None = Field(default=None, max_length=500)


def canonical_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ConsistencyFinding",
    "ConsistencyFindingCode",
    "ConsistencyReport",
    "ConsistencyScope",
    "RepairAction",
    "RepairPlan",
    "RepairResult",
    "canonical_fingerprint",
]
