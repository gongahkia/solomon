# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, cast

from solomon.api.service_models import AnswerRequest, AnswerResponse, PrimitivePlanRequest, PrimitivePlanStep
from solomon.api.services.base import ServiceDelegate
from solomon.api.services.common import build_answer_prompt, digest, plan_explainability_summary
from solomon.currency.models import KnowledgeItem, Matter
from solomon.errors import PolicyRefusalError
from solomon.orchestrator.models import ModelRequest, ModelRouter, RoutedModelResult


class AnswerService(ServiceDelegate):
    def answer(self, request: AnswerRequest, router: ModelRouter) -> AnswerResponse:
        primitive_plan = self.execute_plan(
            PrimitivePlanRequest(
                plan_id=f"answer:{digest({'query': request.query, 'matter_id': request.matter_id})[:16]}",
                steps=[
                    PrimitivePlanStep(
                        primitive="recall",
                        args={
                            "query": request.query,
                            "matter_id": request.matter_id,
                            "client_id": request.client_id,
                            "review_mode": False,
                            "limit": request.limit,
                            "max_context_tokens": request.max_context_tokens,
                        },
                    )
                ],
            )
        )
        recalled = cast(list[dict[str, Any]], primitive_plan.steps[0].result)
        self._enforce_load_bearing_answer_policy(request, recalled)
        prompt = build_answer_prompt(request.query, recalled)
        matter = Matter(
            id=request.matter_id or "ad-hoc",
            client_id=request.client_id or "unknown-client",
            name=request.matter_id or "Ad hoc answer request",
            sensitivity=request.matter_sensitivity,
        )
        routed = self.complete_model_request(
            router,
            ModelRequest(
                prompt=prompt,
                matter_id=request.matter_id,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            ),
            matter=matter,
        )
        self.audit.append(
            "answer_workflow",
            {
                "query_id": request.query,
                "matter_id": request.matter_id,
                "client_id": request.client_id,
                "context_item_ids": [entry["item"]["id"] for entry in recalled],
                "context_count": len(recalled),
                "model": routed.audit.model_dump(mode="json"),
                "boundary": routed.response.metadata.get("boundary", {}),
            },
        )
        return AnswerResponse(
            query=request.query,
            text=routed.response.text,
            model={
                "endpoint": routed.audit.endpoint.value,
                "reason": routed.audit.reason,
                "crossed_boundary": routed.audit.crossed_boundary,
                "fallback_used": routed.audit.fallback_used,
                "quality_caveat": routed.audit.quality_caveat,
                "prompt_sha256": routed.audit.prompt_sha256,
                "prompt_chars": routed.audit.prompt_chars,
                "latency_ms": routed.audit.latency_ms,
                "cost_usd": routed.audit.cost_usd,
                "response_metadata": routed.response.metadata,
            },
            recalled=recalled,
            prompt={
                "context_item_ids": [entry["item"]["id"] for entry in recalled],
                "context_count": len(recalled),
                "boundary_applied": True,
            },
            primitive_plan=plan_explainability_summary(primitive_plan),
        )

    def complete_model_request(
        self,
        router: ModelRouter,
        request: ModelRequest,
        *,
        matter: Matter | None = None,
    ) -> RoutedModelResult:
        context = self.boundary.sanitize_context(request.prompt, matter_id=request.matter_id)
        routed = router.complete(request.model_copy(update={"prompt": context.sanitized_text}), matter=matter)
        demasked = self.boundary.reidentify_response(context.context_id, routed.response.text)
        response = routed.response.model_copy(
            update={
                "text": demasked.text,
                "metadata": {
                    **routed.response.metadata,
                    "boundary": {
                        "context_id": context.context_id,
                        "mapping_count": context.mapping_count,
                        "mapping_flushed": demasked.mapping_flushed,
                        "source_jurisdiction": context.source_jurisdiction,
                        "destination_jurisdiction": context.destination_jurisdiction,
                        "input_mode": context.input_mode,
                    },
                },
            }
        )
        self.audit.append(
            "model_call",
            {
                "matter_id": request.matter_id,
                "endpoint": routed.audit.endpoint.value,
                "crossed_boundary": routed.audit.crossed_boundary,
                "prompt_sha256": routed.audit.prompt_sha256,
                "prompt_chars": routed.audit.prompt_chars,
                "mapping_count": context.mapping_count,
                "mapping_flushed": demasked.mapping_flushed,
            },
        )
        return RoutedModelResult(response=response, audit=routed.audit)

    def _enforce_load_bearing_answer_policy(self, request: AnswerRequest, recalled: list[dict[str, Any]]) -> None:
        refusals: list[dict[str, Any]] = []
        if not recalled:
            refusals.append({"item_id": None, "reasons": ["no live context recalled for load-bearing answer"]})
        for entry in recalled:
            item = KnowledgeItem.model_validate(entry["item"])
            decision = self.credence.load_bearing_decision(item)
            if not decision.allowed:
                refusals.append(decision.model_dump(mode="json"))
        if not refusals:
            return
        self.audit.append(
            "load_bearing_refusal",
            {
                "query_id": request.query,
                "matter_id": request.matter_id,
                "client_id": request.client_id,
                "refusals": refusals,
            },
        )
        reason_text = "; ".join(", ".join(refusal["reasons"]) for refusal in refusals)
        raise PolicyRefusalError(f"load-bearing answer refused: {reason_text}")
