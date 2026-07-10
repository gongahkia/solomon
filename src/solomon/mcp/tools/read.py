# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from solomon.api.service import RecallRequest
from solomon.graph.suggestions import SuggestionDecision
from solomon.mcp.tools.helpers import (
    _audit_metadata,
    _currency_state_for_mcp,
    _filter_impact_scope,
    _log_mcp_call,
    _mcp_log_payload,
    _parse_datetime,
    _review_mcp_output,
    _scope_error_for_item,
)

if TYPE_CHECKING:
    from solomon.mcp.tools.runtime import SolomonMCPRuntime


def preflight_context(
    runtime: SolomonMCPRuntime,
    *,
    query: str,
    matter_id: str | None = None,
    client_id: str | None = None,
    max_items: int = 5,
    max_context_tokens: int | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.preflight_context", caller_id)
    if limited is not None:
        return limited
    results = runtime.service.recall(
        RecallRequest(
            query=query,
            matter_id=matter_id,
            client_id=client_id,
            review_mode=False,
            limit=max_items,
            max_context_tokens=max_context_tokens,
        )
    )
    review = _review_mcp_output(runtime.service, "solomon.preflight_context", results, matter_id=matter_id)
    if "error" in review:
        return review
    entry = runtime.service.audit.append(
        "mcp_call",
        _mcp_log_payload(
            "solomon.preflight_context",
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            boundary_outcome=cast(str | None, review.get("classification")),
            input_payload={
                "query": query,
                "matter_id": matter_id,
                "client_id": client_id,
                "max_items": max_items,
                "max_context_tokens": max_context_tokens,
            },
            metadata={"result_count": len(results)},
        ),
    )
    return {
        "items": results,
        "excluded": [],
        "scope": {"matter_id": matter_id, "client_id": client_id, "caller_id": caller_id},
        "boundary": review,
        "audit": _audit_metadata(entry.seq, entry.entry_hash, runtime.service.audit.path),
    }


def check_currency(
    runtime: SolomonMCPRuntime,
    *,
    knowledge_item_id: str,
    as_of: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.check_currency", caller_id)
    if limited is not None:
        return limited
    scope_error = _scope_error_for_item(
        runtime.service,
        knowledge_item_id,
        matter_id=matter_id,
        client_id=client_id,
        caller_id=caller_id,
    )
    if scope_error is not None:
        return scope_error
    currency = runtime.service.evaluate_currency(knowledge_item_id, as_of=_parse_datetime(as_of))
    trace = runtime.service.why(knowledge_item_id)
    state = _currency_state_for_mcp(str(currency["currency_state"]))
    reasons: list[dict[str, Any]] = [{"explanation": value} for value in currency.get("explanation", [])]
    reasons.extend(cast(list[dict[str, Any]], currency.get("stale_reasons", [])))
    _log_mcp_call(
        runtime.service,
        "solomon.check_currency",
        caller_id=caller_id,
        matter_id=matter_id,
        client_id=client_id,
        currency_outcome=state,
        input_payload={"knowledge_item_id": knowledge_item_id, "as_of": as_of},
    )
    return {
        "knowledge_item_id": knowledge_item_id,
        "state": state,
        "reasons": reasons,
        "last_verified_at": trace.verification.get("last_verified_at"),
        "verified_by": trace.verification.get("verified_by"),
        "successor_id": trace.item.successor_id,
    }


def get_dependencies(
    runtime: SolomonMCPRuntime,
    *,
    knowledge_item_id: str,
    direction: str = "both",
    depth: int = 1,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.get_dependencies", caller_id)
    if limited is not None:
        return limited
    _ = depth
    scope_error = _scope_error_for_item(
        runtime.service,
        knowledge_item_id,
        matter_id=matter_id,
        client_id=client_id,
        caller_id=caller_id,
    )
    if scope_error is not None:
        return scope_error
    trace = runtime.service.why(knowledge_item_id)
    _log_mcp_call(
        runtime.service,
        "solomon.get_dependencies",
        caller_id=caller_id,
        matter_id=matter_id,
        client_id=client_id,
        input_payload={"knowledge_item_id": knowledge_item_id, "direction": direction, "depth": depth},
    )
    return {
        "knowledge_item_id": knowledge_item_id,
        "upstream": trace.dependencies if direction in {"upstream", "both"} else [],
        "downstream": trace.dependents if direction in {"downstream", "both"} else [],
        "truncated": False,
    }


def dependency_suggestions(
    runtime: SolomonMCPRuntime,
    *,
    knowledge_item_id: str,
    decision: str = "pending",
    limit: int = 100,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.dependency_suggestions", caller_id)
    if limited is not None:
        return limited
    item = runtime.service.why(knowledge_item_id).item
    scope_error = _scope_error_for_item(
        runtime.service,
        knowledge_item_id,
        matter_id=matter_id,
        client_id=client_id,
        caller_id=caller_id,
        item=item,
    )
    if scope_error is not None:
        return scope_error
    suggestions = runtime.service.dependency_suggestions(
        item_id=knowledge_item_id,
        decision=SuggestionDecision(decision),
        limit=limit,
    )
    _log_mcp_call(
        runtime.service,
        "solomon.dependency_suggestions",
        caller_id=caller_id,
        matter_id=matter_id,
        client_id=client_id,
        input_payload={"knowledge_item_id": knowledge_item_id, "decision": decision, "limit": limit},
    )
    return {
        "suggestions": [suggestion.model_dump(mode="json") for suggestion in suggestions],
        "scope": {"matter_id": item.matter_id, "client_id": item.client_id, "caller_id": caller_id},
    }


def verification_queue(
    runtime: SolomonMCPRuntime,
    *,
    reviewer_id: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.verification_queue", caller_id)
    if limited is not None:
        return limited
    rows = runtime.service.verification_queue(reviewer_id=reviewer_id, matter_id=matter_id, client_id=client_id)
    _log_mcp_call(
        runtime.service,
        "solomon.verification_queue",
        caller_id=caller_id,
        matter_id=matter_id,
        client_id=client_id,
        input_payload={"reviewer_id": reviewer_id, "matter_id": matter_id, "client_id": client_id},
        metadata={"result_count": len(rows)},
    )
    return {
        "items": rows,
        "scope": {"matter_id": matter_id, "client_id": client_id, "caller_id": caller_id},
    }


def impact(
    runtime: SolomonMCPRuntime,
    *,
    external_authority_id: str,
    as_of: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.impact", caller_id)
    if limited is not None:
        return limited
    result = runtime.service.impact_query(external_authority_id, as_of=_parse_datetime(as_of))
    stale_item_ids, reasons = _filter_impact_scope(
        runtime.service,
        cast(list[str], result["stale_item_ids"]),
        cast(dict[str, list[dict[str, Any]]], result["reasons"]),
        matter_id=matter_id,
        client_id=client_id,
    )
    _log_mcp_call(
        runtime.service,
        "solomon.impact",
        caller_id=caller_id,
        matter_id=matter_id,
        client_id=client_id,
        input_payload={"external_authority_id": external_authority_id, "as_of": as_of},
    )
    return {
        "external_authority_id": external_authority_id,
        "stale_item_ids": stale_item_ids,
        "reasons": reasons,
        "scope": {"matter_id": matter_id, "client_id": client_id, "caller_id": caller_id},
    }
