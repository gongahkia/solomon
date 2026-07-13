# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from solomon.api.service import SolomonService
from solomon.audit.journal import AuditAttribution, AuditEntry
from solomon.currency.models import KnowledgeItem
from solomon.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    PolicyRefusalError,
    SolomonError,
    UpstreamError,
)
from solomon.mcp.auth import current_mcp_call
from solomon.mcp.logging import MCPCallLogRecord, MCPCallStatus, hash_mcp_input


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def _currency_state_for_mcp(value: str) -> str:
    return {
        "Live": "live",
        "StalePendingReverification": "stale_pending",
        "Superseded": "superseded",
        "Retired": "retired",
    }[value]

def _log_mcp_call(
    service: SolomonService,
    tool_name: str,
    *,
    caller_id: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    currency_outcome: str | None = None,
    boundary_outcome: str | None = None,
    input_payload: dict[str, Any] | None = None,
    status: MCPCallStatus = "ok",
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    _append_mcp_call(
        service,
        _mcp_log_payload(
            tool_name,
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            currency_outcome=currency_outcome,
            boundary_outcome=boundary_outcome,
            input_payload=input_payload,
            status=status,
            error_code=error_code,
            metadata=metadata,
        ),
    )


def _append_mcp_call(service: SolomonService, payload: dict[str, Any]) -> AuditEntry:
    context = current_mcp_call()
    attribution = (
        AuditAttribution(actor_id=context.principal.subject, correlation_id=context.correlation_id)
        if context is not None and context.principal is not None
        else None
    )
    return service.audit.append("mcp_call", payload, attribution=attribution)

def _mcp_log_payload(
    tool_name: str,
    *,
    caller_id: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    currency_outcome: str | None = None,
    boundary_outcome: str | None = None,
    input_payload: dict[str, Any] | None = None,
    status: MCPCallStatus = "ok",
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = current_mcp_call()
    resolved_metadata = dict(metadata or {})
    if context is not None and context.principal is not None:
        caller_id = context.principal.subject
        resolved_metadata["identity"] = {
            "roles": sorted({context.principal.role, *context.principal.roles}),
            "scopes": sorted(context.principal.scopes),
        }
    payload = MCPCallLogRecord(
        tool_name=tool_name,
        input_sha256=hash_mcp_input(input_payload or {}),
        status=status,
        caller_id=caller_id,
        matter_id=matter_id,
        client_id=client_id,
        currency_outcome=currency_outcome,
        boundary_outcome=boundary_outcome,
        error_code=error_code,
        metadata=resolved_metadata,
    )
    return payload.model_dump(mode="json")

def _review_mcp_output(
    service: SolomonService,
    tool_name: str,
    payload: object,
    *,
    matter_id: str | None = None,
) -> dict[str, Any]:
    text = _content_text(payload)
    if not text:
        return {"status": "passed", "classification": "SAFE", "finding_count": 0, "context_id": None}
    try:
        with service.telemetry.span(
            "solomon.boundary.review",
            attributes={"solomon.boundary.operation": "mcp_output_review"},
        ):
            response = service.boundary.client.review(
                request={
                    "text": text,
                    "source_jurisdiction": service.boundary.policy.default_source_jurisdiction,
                    "destination_jurisdiction": service.boundary.policy.default_destination_jurisdiction,
                    "document_type": "mcp_tool_result",
                    "review_profile": service.boundary.policy.review_profile,
                    "matter_id": matter_id,
                    "include_suggestions": True,
                }
            )
    except Exception as exc:  # pragma: no cover - client failures are implementation-dependent
        return _error_result(
            "boundary_rejected",
            "boundary review failed; refusing MCP content return",
            retryable=True,
            details={"tool_name": tool_name, "error": str(exc)},
        )
    classification = _response_value(response, "classification", "SAFE")
    findings = _response_value(response, "findings", [])
    finding_count = len(findings) if isinstance(findings, list) else 0
    if classification in service.boundary.policy.unsafe_classifications:
        _append_mcp_call(
            service,
            _mcp_log_payload(
                tool_name,
                matter_id=matter_id,
                status="error",
                boundary_outcome=classification,
                error_code="boundary_rejected",
            ),
        )
        return _error_result(
            "boundary_rejected",
            "boundary classified MCP output as unsafe",
            retryable=False,
            details={"classification": classification, "finding_count": finding_count},
        )
    return {"status": "passed", "classification": classification, "finding_count": finding_count, "context_id": None}

def _scope_error_for_item(
    service: SolomonService,
    item_id: str,
    *,
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
    item: KnowledgeItem | None = None,
) -> dict[str, Any] | None:
    resolved_item = item or service.why(item_id).item
    if matter_id is not None and resolved_item.matter_id != matter_id:
        return _scope_denied(item_id, matter_id=matter_id, client_id=client_id, caller_id=caller_id)
    if client_id is not None and resolved_item.client_id != client_id:
        return _scope_denied(item_id, matter_id=matter_id, client_id=client_id, caller_id=caller_id)
    return None

def _filter_impact_scope(
    service: SolomonService,
    item_ids: list[str],
    reasons: dict[str, list[dict[str, Any]]],
    *,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    if matter_id is None and client_id is None:
        return item_ids, reasons
    filtered_ids: list[str] = []
    filtered_reasons: dict[str, list[dict[str, Any]]] = {}
    for item_id in item_ids:
        item = service.why(item_id).item
        if matter_id is not None and item.matter_id != matter_id:
            continue
        if client_id is not None and item.client_id != client_id:
            continue
        filtered_ids.append(item_id)
        filtered_reasons[item_id] = reasons.get(item_id, [])
    return filtered_ids, filtered_reasons

def _scope_denied(
    item_id: str,
    *,
    matter_id: str | None,
    client_id: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    return _error_result(
        "scope_denied",
        "caller is not allowed to access this MCP scope",
        retryable=False,
        details={
            "knowledge_item_id": item_id,
            "matter_id": matter_id,
            "client_id": client_id,
            "caller_id": caller_id,
        },
    )

def _content_text(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        chunks: list[str] = []
        for entry in payload:
            if isinstance(entry, dict):
                item = entry.get("item")
                if isinstance(item, dict) and isinstance(item.get("content"), str):
                    chunks.append(item["content"])
        return "\n\n".join(chunks)
    return ""

def _response_value(response: object, field: str, default: Any) -> Any:
    if isinstance(response, dict):
        return response.get(field, default)
    value = getattr(response, field, default)
    return getattr(value, "value", value)

def structured_tool_errors(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @wraps(function)
    def invoke(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return function(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return _exception_error_result(exc)

    return invoke


def _error_result(
    code: str,
    message: str,
    *,
    retryable: bool,
    details: dict[str, Any],
    category: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "category": category or _error_category(code),
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details,
        },
    }


def _exception_error_result(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ValidationError | ValueError | BadRequestError):
        return _error_result("validation_failed", "MCP tool request failed validation", retryable=False, details={})
    if isinstance(exc, PolicyRefusalError):
        return _error_result("authorization_denied", "MCP tool request was denied", retryable=False, details={})
    if isinstance(exc, NotFoundError | KeyError):
        return _error_result("state_not_found", "MCP tool requested unavailable state", retryable=False, details={})
    if isinstance(exc, ConflictError):
        return _error_result(
            "invalid_state",
            "MCP tool request conflicts with current state",
            retryable=False,
            details={},
        )
    if isinstance(exc, UpstreamError):
        return _error_result("upstream_failure", "MCP tool upstream dependency failed", retryable=True, details={})
    if isinstance(exc, TimeoutError | ConnectionError | OSError):
        return _error_result("upstream_failure", "MCP tool upstream dependency failed", retryable=True, details={})
    if isinstance(exc, SolomonError):
        return _error_result("internal_failure", "MCP tool request failed", retryable=False, details={})
    return _error_result("internal_failure", "MCP tool request failed", retryable=False, details={})


def _error_category(code: str) -> str:
    if code in {"invalid_request", "bad_request", "validation_failed"}:
        return "validation"
    if code in {"scope_denied", "authorization_denied", "policy_refusal"}:
        return "authorization"
    if code in {"not_found", "state_not_found", "invalid_state"}:
        return "state"
    if code in {"upstream_failure", "boundary_rejected"}:
        return "upstream"
    if code == "rate_limited":
        return "rate_limit"
    return "internal"

def _audit_metadata(seq: int, entry_hash: str, journal_path: Path) -> dict[str, str]:
    return {"entry_id": str(seq), "entry_hash": entry_hash, "journal_path": str(journal_path)}

def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
