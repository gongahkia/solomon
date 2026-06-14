# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import Field

from solomon.api.schemas import SolomonModel

JsonObject: TypeAlias = dict[str, Any]
JsonSchema: TypeAlias = dict[str, Any]
SchemaPair: TypeAlias = tuple[type[SolomonModel], type[SolomonModel]]

CurrencyStateValue: TypeAlias = Literal["live", "stale_pending", "superseded", "retired"]
DependencyDirection: TypeAlias = Literal["upstream", "downstream", "both"]
DependencySuggestionDecision: TypeAlias = Literal["pending", "confirmed", "rejected"]
AuditPackFormat: TypeAlias = Literal["json", "pdf"]
VerificationDecision: TypeAlias = Literal["reaffirm", "supersede", "retire", "pin"]


class EffectiveScope(SolomonModel):
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class IngestScope(SolomonModel):
    matter_id: str | None = None
    client_id: str | None = None
    jurisdiction: str | None = None


class BoundaryMetadata(SolomonModel):
    status: Literal["passed", "rejected", "not_applicable"]
    classification: str | None = None
    finding_count: int = Field(default=0, ge=0)
    context_id: str | None = None


class AuditMetadata(SolomonModel):
    entry_id: str | None = None
    entry_hash: str | None = None
    journal_path: str | None = None


class ExcludedContextItem(SolomonModel):
    item_id: str | None = None
    reason: str
    code: str | None = None


class PreflightContextInput(SolomonModel):
    query: str = Field(min_length=1)
    matter_id: str | None = None
    client_id: str | None = None
    max_items: int = Field(default=5, ge=1, le=50)
    max_context_tokens: int | None = Field(default=None, ge=1)
    caller_id: str | None = None


class PreflightContextOutput(SolomonModel):
    items: list[JsonObject]
    excluded: list[ExcludedContextItem] = Field(default_factory=list)
    scope: EffectiveScope
    boundary: BoundaryMetadata
    audit: AuditMetadata | None = None


class CheckCurrencyInput(SolomonModel):
    knowledge_item_id: str = Field(min_length=1)
    as_of: str | None = None
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class CheckCurrencyOutput(SolomonModel):
    knowledge_item_id: str
    state: CurrencyStateValue
    reasons: list[JsonObject] = Field(default_factory=list)
    last_verified_at: str | None = None
    verified_by: str | None = None
    successor_id: str | None = None


class GetDependenciesInput(SolomonModel):
    knowledge_item_id: str = Field(min_length=1)
    direction: DependencyDirection = "both"
    depth: int = Field(default=1, ge=1, le=8)
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class GetDependenciesOutput(SolomonModel):
    knowledge_item_id: str
    upstream: list[JsonObject] = Field(default_factory=list)
    downstream: list[JsonObject] = Field(default_factory=list)
    truncated: bool = False


class VerifyPositionInput(SolomonModel):
    knowledge_item_id: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    decision: VerificationDecision
    evidence_ref: str = Field(min_length=1)
    successor_id: str | None = None
    recorded_at: str | None = None
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class VerifyPositionOutput(SolomonModel):
    item: JsonObject
    currency: JsonObject
    audit: AuditMetadata


class IngestInput(SolomonModel):
    text: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    scope: IngestScope
    kind: Literal["position", "clause", "house-view", "advice", "note"] = "note"
    source_kind: Literal["partner", "associate", "matter-doc", "external-feed", "model"] = "associate"
    author: str | None = None
    caller_id: str | None = None


class IngestOutput(SolomonModel):
    item: JsonObject
    boundary: BoundaryMetadata
    dependency_suggestions: list[JsonObject] = Field(default_factory=list)
    audit: AuditMetadata | None = None


class AuditPackInput(SolomonModel):
    knowledge_item_id: str = Field(min_length=1)
    format: AuditPackFormat = "json"
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class AuditPackOutput(SolomonModel):
    knowledge_item_id: str
    format: AuditPackFormat
    pack: JsonObject | str
    hash_chain: JsonObject


class DependencySuggestionsInput(SolomonModel):
    knowledge_item_id: str = Field(min_length=1)
    decision: DependencySuggestionDecision = "pending"
    limit: int = Field(default=100, ge=1, le=500)
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class DependencySuggestionsOutput(SolomonModel):
    suggestions: list[JsonObject]
    scope: EffectiveScope


class ImpactInput(SolomonModel):
    external_authority_id: str = Field(min_length=1)
    as_of: str | None = None
    matter_id: str | None = None
    client_id: str | None = None
    caller_id: str | None = None


class ImpactOutput(SolomonModel):
    external_authority_id: str
    stale_item_ids: list[str] = Field(default_factory=list)
    reasons: dict[str, list[JsonObject]] = Field(default_factory=dict)
    scope: EffectiveScope


class HealthInput(SolomonModel):
    caller_id: str | None = None


class HealthOutput(SolomonModel):
    version: str
    store: JsonObject
    journal: JsonObject
    boundary: JsonObject


TOOL_SCHEMA_MODELS: dict[str, SchemaPair] = {
    "solomon.health": (HealthInput, HealthOutput),
    "solomon.preflight_context": (PreflightContextInput, PreflightContextOutput),
    "solomon.check_currency": (CheckCurrencyInput, CheckCurrencyOutput),
    "solomon.get_dependencies": (GetDependenciesInput, GetDependenciesOutput),
    "solomon.verify_position": (VerifyPositionInput, VerifyPositionOutput),
    "solomon.ingest": (IngestInput, IngestOutput),
    "solomon.audit_pack": (AuditPackInput, AuditPackOutput),
    "solomon.dependency_suggestions": (DependencySuggestionsInput, DependencySuggestionsOutput),
    "solomon.impact": (ImpactInput, ImpactOutput),
}


def json_schema_for_tool(tool_name: str) -> JsonSchema:
    input_model, output_model = TOOL_SCHEMA_MODELS[tool_name]
    return {
        "input": input_model.model_json_schema(),
        "output": output_model.model_json_schema(),
    }


MCP_TOOL_JSON_SCHEMAS: dict[str, JsonSchema] = {
    tool_name: json_schema_for_tool(tool_name) for tool_name in TOOL_SCHEMA_MODELS
}


__all__ = [
    "AuditPackInput",
    "AuditPackOutput",
    "CheckCurrencyInput",
    "CheckCurrencyOutput",
    "DependencySuggestionsInput",
    "DependencySuggestionsOutput",
    "GetDependenciesInput",
    "GetDependenciesOutput",
    "HealthInput",
    "HealthOutput",
    "ImpactInput",
    "ImpactOutput",
    "IngestInput",
    "IngestOutput",
    "MCP_TOOL_JSON_SCHEMAS",
    "PreflightContextInput",
    "PreflightContextOutput",
    "TOOL_SCHEMA_MODELS",
    "VerifyPositionInput",
    "VerifyPositionOutput",
    "json_schema_for_tool",
]
