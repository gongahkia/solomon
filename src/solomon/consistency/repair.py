# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from solomon.audit.journal import AuditAttribution
from solomon.consistency.inspection import ConsistencyInspector
from solomon.consistency.models import (
    ConsistencyFindingCode,
    ConsistencyReport,
    ConsistencyScope,
    RepairAction,
    RepairPlan,
    RepairResult,
)


class ConsistencyRepairService:
    """Plans safe, provenance-preserving repairs and refuses every other inconsistency."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._inspector = ConsistencyInspector(service)

    def plan(self, scope: ConsistencyScope) -> RepairPlan:
        report = self._inspector.check(scope)
        return self.plan_report(report)

    def plan_report(self, report: ConsistencyReport) -> RepairPlan:
        actions: list[RepairAction] = []
        blocked_assertions: set[str] = set()
        for finding in report.findings:
            if finding.code not in {
                ConsistencyFindingCode.EDGE_INVALID_PROVENANCE,
                ConsistencyFindingCode.SOURCE_VERSION_UNRECONSTRUCTIBLE,
                ConsistencyFindingCode.SCOPE_MISMATCH,
            }:
                continue
            if finding.resource_type == "dependency_assertion":
                blocked_assertions.add(finding.resource_id)
            blocked_assertions.update(finding.related_ids)
        for finding in report.findings:
            if not finding.repairable or finding.resource_id in blocked_assertions:
                continue
            if finding.code is ConsistencyFindingCode.CONFIRMED_ASSERTION_MISSING_EDGE:
                actions.append(
                    RepairAction(
                        action="reproject_confirmed_assertion_edge",
                        finding_code=finding.code,
                        assertion_id=finding.resource_id,
                    )
                )
            if (
                finding.code is ConsistencyFindingCode.SOURCE_REVISION_OPERATION_MISSING
                and len(finding.related_ids) == 2
            ):
                actions.append(
                    RepairAction(
                        action="schedule_source_reverification",
                        finding_code=finding.code,
                        assertion_id=finding.resource_id,
                        previous_document_id=finding.related_ids[0],
                        replacement_document_id=finding.related_ids[1],
                    )
                )
        return RepairPlan.create(
            scope=report.scope,
            report_fingerprint=report.fingerprint,
            actions=actions,
        )

    def apply(self, plan: RepairPlan) -> RepairResult:
        if not plan.valid_fingerprint():
            return self._refuse(plan, "repair plan fingerprint is invalid")
        if plan.scope.tenant_id != self._service.tenant_id:
            return self._refuse(plan, "repair plan tenant does not match the active service scope")
        applied_marker = f"repair:{plan.fingerprint}"
        for entry in self._service.audit.list_entries():
            if entry.event_type == "consistency_repair_applied" and entry.payload.get("operation_id") == applied_marker:
                return RepairResult(plan_fingerprint=plan.fingerprint, applied=True, idempotent=True)
        report = self._inspector.check(plan.scope)
        expected = self.plan_report(report)
        if report.fingerprint != plan.report_fingerprint:
            return self._refuse(plan, "repair plan is stale because scoped consistency state changed")
        if expected.actions != plan.actions:
            return self._refuse(plan, "repair plan actions no longer match safe scoped findings")
        for action in plan.actions:
            self._apply_action(action, plan.scope)
        self._service.audit.append_idempotent(
            "consistency_repair_applied",
            {
                "plan_fingerprint": plan.fingerprint,
                "report_fingerprint": plan.report_fingerprint,
                "scope_key": plan.scope.key,
                "action_count": len(plan.actions),
            },
            operation_id=applied_marker,
            attribution=AuditAttribution(actor_id="system:consistency-repair", correlation_id=plan.fingerprint),
        )
        return RepairResult(plan_fingerprint=plan.fingerprint, applied=True, actions_applied=plan.actions)

    def _apply_action(self, action: RepairAction, scope: ConsistencyScope) -> None:
        if action.action == "reproject_confirmed_assertion_edge" and action.assertion_id is not None:
            self._service._authority.repair_confirmed_assertion_edge(
                action.assertion_id,
                matter_id=scope.matter_id,
                client_id=scope.client_id,
            )
            return
        if (
            action.action == "schedule_source_reverification"
            and action.previous_document_id is not None
            and action.replacement_document_id is not None
        ):
            self._service._authority.mark_dependency_assertions_for_source_revision(
                previous_document_id=action.previous_document_id,
                replacement_document_id=action.replacement_document_id,
            )
            return
        raise ValueError("repair plan contains an unsupported action")

    @staticmethod
    def _refuse(plan: RepairPlan, reason: str) -> RepairResult:
        return RepairResult(plan_fingerprint=plan.fingerprint, applied=False, refusal=reason)


__all__ = ["ConsistencyRepairService"]
