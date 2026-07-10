# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from solomon.api.service import IngestRequest, PinRequest, VerificationRequest
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.suggestions import SuggestionDecision
from solomon.mcp.tools.helpers import (
    _audit_metadata,
    _currency_state_for_mcp,
    _mcp_log_payload,
    _parse_datetime,
    _review_mcp_output,
    _scope_error_for_item,
    _sha256,
)

if TYPE_CHECKING:
    from solomon.mcp.tools.runtime import SolomonMCPRuntime


def verify_position(
    runtime: SolomonMCPRuntime,
    *,
    knowledge_item_id: str,
    verifier_id: str,
    decision: str,
    evidence_ref: str,
    successor_id: str | None = None,
    recorded_at: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.verify_position", caller_id)
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
    if decision == "pin":
        item = runtime.service.pin(
            knowledge_item_id,
            PinRequest(lawyer_id=verifier_id, reason=evidence_ref, pinned_at=_parse_datetime(recorded_at)),
        )
    else:
        item = runtime.service.record_verification(
            knowledge_item_id,
                VerificationRequest(
                    by=verifier_id,
                    outcome=VerificationOutcome(decision),
                    basis=evidence_ref,
                    source_ref=evidence_ref,
                    successor_id=successor_id,
                    recorded_at=_parse_datetime(recorded_at),
                ),
        )
    currency = runtime.service.evaluate_currency(knowledge_item_id)
    entry = runtime.service.audit.append(
        "mcp_call",
        _mcp_log_payload(
            "solomon.verify_position",
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            currency_outcome=_currency_state_for_mcp(str(currency["currency_state"])),
            input_payload={
                "knowledge_item_id": knowledge_item_id,
                "decision": decision,
                "successor_id": successor_id,
                "recorded_at": recorded_at,
            },
            metadata={"evidence_ref_sha256": _sha256(evidence_ref)},
        ),
    )
    return {
        "item": item.model_dump(mode="json"),
        "currency": {
            **currency,
            "state": _currency_state_for_mcp(str(currency["currency_state"])),
        },
        "audit": _audit_metadata(entry.seq, entry.entry_hash, runtime.service.audit.path),
    }


def ingest(
    runtime: SolomonMCPRuntime,
    *,
    text: str,
    source_ref: str,
    scope: dict[str, Any],
    kind: str = "note",
    source_kind: str = "associate",
    author: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.ingest", caller_id)
    if limited is not None:
        return limited
    item = runtime.service.ingest(
        IngestRequest(
            kind=KnowledgeKind(kind),
            content=text,
            source_kind=SourceKind(source_kind),
            source_ref=source_ref,
            author=author,
            matter_id=cast(str | None, scope.get("matter_id")),
            client_id=cast(str | None, scope.get("client_id")),
        )
    )
    review = _review_mcp_output(runtime.service, "solomon.ingest", item.content, matter_id=item.matter_id)
    if "error" in review:
        return review
    suggestions = runtime.service.dependency_suggestions(item_id=item.id, decision=SuggestionDecision.PENDING)
    entry = runtime.service.audit.append(
        "mcp_call",
        _mcp_log_payload(
            "solomon.ingest",
            caller_id=caller_id,
            matter_id=item.matter_id,
            client_id=item.client_id,
            boundary_outcome=cast(str | None, review.get("classification")),
            input_payload={
                "source_ref": source_ref,
                "scope": scope,
                "kind": kind,
                "source_kind": source_kind,
                "author": author,
            },
            metadata={"item_id": item.id},
        ),
    )
    return {
        "item": item.model_dump(mode="json"),
        "boundary": review,
        "dependency_suggestions": [suggestion.model_dump(mode="json") for suggestion in suggestions],
        "audit": _audit_metadata(entry.seq, entry.entry_hash, runtime.service.audit.path),
    }
