# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any

from solomon.api.service_models import (
    PrimitivePlanExecution,
    PrimitivePlanRequest,
    PrimitivePlanStep,
    PrimitiveStepResult,
    RecallRequest,
    VerificationRequest,
    WhyTrace,
)
from solomon.api.services.base import ServiceDelegate
from solomon.api.services.common import digest, jsonable, parse_iso_datetime, result_summary
from solomon.currency.contradiction import contradictions_for_item
from solomon.currency.engine import evaluate_currency
from solomon.currency.verification import verification_history
from solomon.errors import BadRequestError
from solomon.orchestrator.retrieval import MatterContext, RecallOptions


class RecallService(ServiceDelegate):
    def recall(self, request: RecallRequest) -> list[dict[str, Any]]:
        results = self.retrieval.recall(
            request.query,
            matter_context=MatterContext(matter_id=request.matter_id, client_id=request.client_id),
            options=RecallOptions(
                limit=request.limit,
                review_mode=request.review_mode,
                max_context_tokens=request.max_context_tokens,
            ),
        )
        self.audit.log_query(query_id=request.query, results=results)
        return [result.model_dump(mode="json") for result in results]

    def why(self, item_id: str, *, as_of: datetime | None = None) -> WhyTrace:
        item = self._get_item(item_id)
        history = verification_history(item)
        return WhyTrace(
            item=item,
            currency=evaluate_currency(item, as_of=as_of).model_dump(mode="json"),
            dependencies=[edge.model_dump(mode="json") for edge in self.graph.get_dependencies(item.id)],
            dependents=[edge.model_dump(mode="json") for edge in self.graph.get_dependents(item.id)],
            contradictions=[signal.model_dump(mode="json") for signal in contradictions_for_item(item)],
            provenance=item.provenance.model_dump(mode="json"),
            credence_tier=item.credence_tier.value,
            verification={
                "verified_state": item.verified_state.value,
                "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
                "verified_by": item.verified_by,
                "reviewer_id": item.metadata.get("verification_reviewer_id"),
                "status": item.metadata.get("verification_status"),
                "history": [event.model_dump(mode="json") for event in history],
                "verification_policy_version": self.verification_policy_version,
                "credence_policy_version": self.credence_policy_version,
            },
        )

    def timeline(self, request: RecallRequest, *, as_of: str) -> list[dict[str, Any]]:
        results = self.retrieval.timeline(
            request.query,
            as_of=parse_iso_datetime(as_of),
            options=RecallOptions(
                limit=request.limit,
                review_mode=True,
                max_context_tokens=request.max_context_tokens,
            ),
        )
        return [result.model_dump(mode="json") for result in results]

    def execute_plan(self, request: PrimitivePlanRequest) -> PrimitivePlanExecution:
        plan_id = request.plan_id or f"plan:{digest(request.model_dump(mode='json'))[:16]}"
        store_state_sha256 = self._store_state_sha256()
        step_results: list[PrimitiveStepResult] = []
        for index, step in enumerate(request.steps, start=1):
            result = jsonable(self._execute_primitive(step))
            step_results.append(
                PrimitiveStepResult(
                    index=index,
                    primitive=step.primitive,
                    args_sha256=digest(step.args),
                    result_sha256=digest(result),
                    result_summary=result_summary(result),
                    result=result,
                )
            )
        audit_entry = self.audit.append(
            "primitive_plan",
            {
                "schema_id": "solomon.primitive_plan_execution.v1",
                "plan_id": plan_id,
                "plan_sha256": digest(request.model_dump(mode="json")),
                "store_state_sha256": store_state_sha256,
                "steps": [
                    {
                        "index": result.index,
                        "primitive": result.primitive,
                        "args_sha256": result.args_sha256,
                        "result_sha256": result.result_sha256,
                        "result_summary": result.result_summary,
                    }
                    for result in step_results
                ],
            },
        )
        return PrimitivePlanExecution(
            plan_id=plan_id,
            plan=request.model_copy(update={"plan_id": plan_id}),
            store_state_sha256=store_state_sha256,
            steps=step_results,
            audit_event_hash=audit_entry.entry_hash,
        )

    def _execute_primitive(self, step: PrimitivePlanStep) -> Any:
        if step.primitive == "recall":
            return self.recall(RecallRequest.model_validate(step.args))
        if step.primitive == "evaluate_currency":
            _ensure_subset_args(step, {"item_id", "as_of"})
            _ensure_arg(step, "item_id")
            return self.evaluate_currency(
                _required_arg(step, "item_id"),
                as_of=_optional_datetime_arg(step, "as_of") or self._deterministic_store_timestamp(),
            )
        if step.primitive == "impact_query":
            _ensure_subset_args(step, {"authority_id", "as_of"})
            _ensure_arg(step, "authority_id")
            return self.impact_query(
                _required_arg(step, "authority_id"),
                as_of=_optional_datetime_arg(step, "as_of") or self._deterministic_store_timestamp(),
            )
        if step.primitive == "timeline":
            _ensure_arg(step, "as_of")
            timeline_args = dict(step.args)
            as_of = str(timeline_args.pop("as_of"))
            return self.timeline(RecallRequest.model_validate(timeline_args), as_of=as_of)
        if step.primitive == "record_verification":
            _ensure_arg(step, "item_id")
            _ensure_arg(step, "recorded_at")
            verification_args = dict(step.args)
            item_id = str(verification_args.pop("item_id"))
            return self.record_verification(item_id, VerificationRequest.model_validate(verification_args))
        if step.primitive == "why":
            _ensure_subset_args(step, {"item_id", "as_of"})
            _ensure_arg(step, "item_id")
            return self.why(
                _required_arg(step, "item_id"),
                as_of=_optional_datetime_arg(step, "as_of") or self._deterministic_store_timestamp(),
            )
        raise BadRequestError(f"unsupported primitive: {step.primitive}")


def _ensure_subset_args(step: PrimitivePlanStep, allowed: set[str]) -> None:
    extra = sorted(set(step.args) - allowed)
    if extra:
        raise BadRequestError(f"{step.primitive} got unsupported args: {', '.join(extra)}")


def _ensure_arg(step: PrimitivePlanStep, name: str) -> None:
    if name not in step.args or step.args[name] is None:
        raise BadRequestError(f"{step.primitive} requires arg: {name}")


def _required_arg(step: PrimitivePlanStep, name: str) -> str:
    _ensure_arg(step, name)
    return str(step.args[name])


def _optional_datetime_arg(step: PrimitivePlanStep, name: str) -> datetime | None:
    raw = step.args.get(name)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    return parse_iso_datetime(str(raw))
