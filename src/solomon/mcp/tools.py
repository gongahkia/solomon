# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol, cast

from mcp.types import ToolAnnotations

from solomon.api.schemas import SolomonModel
from solomon.api.service import IngestRequest, PinRequest, RecallRequest, SolomonService, VerificationRequest
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.suggestions import SuggestionDecision
from solomon.mcp.schemas import MCP_TOOL_JSON_SCHEMAS, JsonSchema


class MCPToolSpec(SolomonModel):
    name: str
    description: str
    read_only: bool
    input_schema: JsonSchema
    output_schema: JsonSchema


TOOL_DESCRIPTIONS: dict[str, str] = {
    "solomon.preflight_context": "Return current, scoped firm context safe to inject into a prompt.",
    "solomon.check_currency": "Check whether a knowledge item is live, stale-pending, superseded, or retired.",
    "solomon.get_dependencies": "Return upstream and downstream dependency edges for a knowledge item.",
    "solomon.verify_position": "Record a human verification decision with evidence.",
    "solomon.ingest": "Boundary-check and ingest new firm knowledge.",
    "solomon.audit_pack": "Export provenance, dependency, verification, boundary, and hash-chain evidence.",
    "solomon.dependency_suggestions": "Return proposed dependency edges for human confirmation.",
    "solomon.impact": "Return internal items affected by a changed external authority.",
}

READ_ONLY_TOOLS = {
    "solomon.preflight_context",
    "solomon.check_currency",
    "solomon.get_dependencies",
    "solomon.audit_pack",
    "solomon.dependency_suggestions",
    "solomon.impact",
}


class FastMCPProtocol(Protocol):
    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Any] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


class SolomonMCPRuntime:
    def __init__(self, service: SolomonService) -> None:
        self.service = service

    def preflight_context(
        self,
        *,
        query: str,
        matter_id: str | None = None,
        client_id: str | None = None,
        max_items: int = 5,
        max_context_tokens: int | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        results = self.service.recall(
            RecallRequest(
                query=query,
                matter_id=matter_id,
                client_id=client_id,
                review_mode=False,
                limit=max_items,
                max_context_tokens=max_context_tokens,
            )
        )
        entry = self.service.audit.append(
            "mcp_call",
            {
                "tool_name": "solomon.preflight_context",
                "caller_id": caller_id,
                "matter_id": matter_id,
                "client_id": client_id,
                "result_count": len(results),
            },
        )
        return {
            "items": results,
            "excluded": [],
            "scope": {"matter_id": matter_id, "client_id": client_id, "caller_id": caller_id},
            "boundary": {"status": "not_applicable", "classification": None, "finding_count": 0, "context_id": None},
            "audit": _audit_metadata(entry.seq, entry.entry_hash, self.service.audit.path),
        }

    def check_currency(
        self,
        *,
        knowledge_item_id: str,
        as_of: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        currency = self.service.evaluate_currency(knowledge_item_id, as_of=_parse_datetime(as_of))
        trace = self.service.why(knowledge_item_id)
        state = _currency_state_for_mcp(str(currency["currency_state"]))
        reasons: list[dict[str, Any]] = [{"explanation": value} for value in currency.get("explanation", [])]
        reasons.extend(cast(list[dict[str, Any]], currency.get("stale_reasons", [])))
        _log_mcp_call(self.service, "solomon.check_currency", caller_id=caller_id, currency_outcome=state)
        return {
            "knowledge_item_id": knowledge_item_id,
            "state": state,
            "reasons": reasons,
            "last_verified_at": trace.verification.get("last_verified_at"),
            "verified_by": trace.verification.get("verified_by"),
            "successor_id": trace.item.successor_id,
        }

    def get_dependencies(
        self,
        *,
        knowledge_item_id: str,
        direction: str = "both",
        depth: int = 1,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        _ = depth
        trace = self.service.why(knowledge_item_id)
        _log_mcp_call(self.service, "solomon.get_dependencies", caller_id=caller_id)
        return {
            "knowledge_item_id": knowledge_item_id,
            "upstream": trace.dependencies if direction in {"upstream", "both"} else [],
            "downstream": trace.dependents if direction in {"downstream", "both"} else [],
            "truncated": False,
        }

    def verify_position(
        self,
        *,
        knowledge_item_id: str,
        verifier_id: str,
        decision: str,
        evidence_ref: str,
        successor_id: str | None = None,
        recorded_at: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        if decision == "pin":
            item = self.service.pin(
                knowledge_item_id,
                PinRequest(lawyer_id=verifier_id, reason=evidence_ref, pinned_at=_parse_datetime(recorded_at)),
            )
        else:
            item = self.service.record_verification(
                knowledge_item_id,
                VerificationRequest(
                    by=verifier_id,
                    outcome=VerificationOutcome(decision),
                    successor_id=successor_id,
                    recorded_at=_parse_datetime(recorded_at),
                ),
            )
        currency = self.service.evaluate_currency(knowledge_item_id)
        entry = self.service.audit.append(
            "mcp_call",
            {
                "tool_name": "solomon.verify_position",
                "caller_id": caller_id,
                "item_id": knowledge_item_id,
                "decision": decision,
                "evidence_ref_sha256": _sha256(evidence_ref),
            },
        )
        return {
            "item": item.model_dump(mode="json"),
            "currency": {
                **currency,
                "state": _currency_state_for_mcp(str(currency["currency_state"])),
            },
            "audit": _audit_metadata(entry.seq, entry.entry_hash, self.service.audit.path),
        }

    def ingest(
        self,
        *,
        text: str,
        source_ref: str,
        scope: dict[str, Any],
        kind: str = "note",
        source_kind: str = "associate",
        author: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        item = self.service.ingest(
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
        suggestions = self.service.dependency_suggestions(item_id=item.id, decision=SuggestionDecision.PENDING)
        entry = self.service.audit.append(
            "mcp_call",
            {
                "tool_name": "solomon.ingest",
                "caller_id": caller_id,
                "item_id": item.id,
                "matter_id": item.matter_id,
                "client_id": item.client_id,
            },
        )
        return {
            "item": item.model_dump(mode="json"),
            "boundary": {
                "status": "passed",
                "classification": item.provenance.boundary_review_classification,
                "finding_count": len(item.provenance.boundary_findings),
                "context_id": None,
            },
            "dependency_suggestions": [suggestion.model_dump(mode="json") for suggestion in suggestions],
            "audit": _audit_metadata(entry.seq, entry.entry_hash, self.service.audit.path),
        }

    def audit_pack(
        self,
        *,
        knowledge_item_id: str,
        format: str = "json",
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        _ = self.service.why(knowledge_item_id)
        with TemporaryDirectory(prefix="solomon-mcp-audit-") as temp_dir:
            pack_dir = self.service.export_audit_pack(Path(temp_dir))
            manifest = (pack_dir / "manifest.json").read_text(encoding="utf-8")
        entry = self.service.audit.append(
            "mcp_call",
            {"tool_name": "solomon.audit_pack", "caller_id": caller_id, "item_id": knowledge_item_id, "format": format},
        )
        return {
            "knowledge_item_id": knowledge_item_id,
            "format": format,
            "pack": manifest if format == "pdf" else {"manifest_json": manifest},
            "hash_chain": {"entry_hash": entry.entry_hash},
        }

    def dependency_suggestions(
        self,
        *,
        knowledge_item_id: str,
        decision: str = "pending",
        limit: int = 100,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        item = self.service.why(knowledge_item_id).item
        suggestions = self.service.dependency_suggestions(
            item_id=knowledge_item_id,
            decision=SuggestionDecision(decision),
            limit=limit,
        )
        _log_mcp_call(self.service, "solomon.dependency_suggestions", caller_id=caller_id)
        return {
            "suggestions": [suggestion.model_dump(mode="json") for suggestion in suggestions],
            "scope": {"matter_id": item.matter_id, "client_id": item.client_id, "caller_id": caller_id},
        }

    def impact(
        self,
        *,
        external_authority_id: str,
        as_of: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.service.impact_query(external_authority_id, as_of=_parse_datetime(as_of))
        _log_mcp_call(
            self.service,
            "solomon.impact",
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
        )
        return {
            "external_authority_id": external_authority_id,
            "stale_item_ids": result["stale_item_ids"],
            "reasons": result["reasons"],
            "scope": {"matter_id": matter_id, "client_id": client_id, "caller_id": caller_id},
        }


def mcp_tool_specs() -> list[MCPToolSpec]:
    return [
        MCPToolSpec(
            name=tool_name,
            description=TOOL_DESCRIPTIONS[tool_name],
            read_only=tool_name in READ_ONLY_TOOLS,
            input_schema=schemas["input"],
            output_schema=schemas["output"],
        )
        for tool_name, schemas in MCP_TOOL_JSON_SCHEMAS.items()
    ]


def register_solomon_tools(server: FastMCPProtocol, runtime: SolomonMCPRuntime) -> None:
    def annotations_for(tool_name: str) -> ToolAnnotations:
        read_only = tool_name in READ_ONLY_TOOLS
        return ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=not read_only,
            idempotentHint=read_only,
            openWorldHint=False,
        )

    server.tool(
        name="solomon.preflight_context",
        description=TOOL_DESCRIPTIONS["solomon.preflight_context"],
        annotations=annotations_for("solomon.preflight_context"),
        structured_output=True,
    )(runtime.preflight_context)
    server.tool(
        name="solomon.check_currency",
        description=TOOL_DESCRIPTIONS["solomon.check_currency"],
        annotations=annotations_for("solomon.check_currency"),
        structured_output=True,
    )(runtime.check_currency)
    server.tool(
        name="solomon.get_dependencies",
        description=TOOL_DESCRIPTIONS["solomon.get_dependencies"],
        annotations=annotations_for("solomon.get_dependencies"),
        structured_output=True,
    )(runtime.get_dependencies)
    server.tool(
        name="solomon.verify_position",
        description=TOOL_DESCRIPTIONS["solomon.verify_position"],
        annotations=annotations_for("solomon.verify_position"),
        structured_output=True,
    )(runtime.verify_position)
    server.tool(
        name="solomon.ingest",
        description=TOOL_DESCRIPTIONS["solomon.ingest"],
        annotations=annotations_for("solomon.ingest"),
        structured_output=True,
    )(runtime.ingest)
    server.tool(
        name="solomon.audit_pack",
        description=TOOL_DESCRIPTIONS["solomon.audit_pack"],
        annotations=annotations_for("solomon.audit_pack"),
        structured_output=True,
    )(runtime.audit_pack)
    server.tool(
        name="solomon.dependency_suggestions",
        description=TOOL_DESCRIPTIONS["solomon.dependency_suggestions"],
        annotations=annotations_for("solomon.dependency_suggestions"),
        structured_output=True,
    )(runtime.dependency_suggestions)
    server.tool(
        name="solomon.impact",
        description=TOOL_DESCRIPTIONS["solomon.impact"],
        annotations=annotations_for("solomon.impact"),
        structured_output=True,
    )(runtime.impact)


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
) -> None:
    service.audit.append(
        "mcp_call",
        {
            "tool_name": tool_name,
            "caller_id": caller_id,
            "matter_id": matter_id,
            "client_id": client_id,
            "currency_outcome": currency_outcome,
        },
    )


def _audit_metadata(seq: int, entry_hash: str, journal_path: Path) -> dict[str, str]:
    return {"entry_id": str(seq), "entry_hash": entry_hash, "journal_path": str(journal_path)}


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "MCPToolSpec",
    "READ_ONLY_TOOLS",
    "SolomonMCPRuntime",
    "TOOL_DESCRIPTIONS",
    "register_solomon_tools",
    "mcp_tool_specs",
]
