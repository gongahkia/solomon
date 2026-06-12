# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.engine import evaluate_currency
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeContentRole,
    KnowledgeItem,
    SourceKind,
    VerifiedState,
    now_utc,
)


class CredenceAction(str, Enum):
    ASSIGN = "assign"
    PROMOTE = "promote"
    DEMOTE = "demote"


class CredencePolicy(SolomonModel):
    source_tiers: dict[SourceKind, CredenceTier] = Field(
        default_factory=lambda: {
            SourceKind.PARTNER: CredenceTier.FIRM_AUTHORITATIVE,
            SourceKind.ASSOCIATE: CredenceTier.VERIFIED,
            SourceKind.MATTER_DOC: CredenceTier.VERIFIED,
            SourceKind.EXTERNAL_FEED: CredenceTier.VERIFIED,
            SourceKind.MODEL: CredenceTier.MODEL_INFERRED,
        }
    )
    tier_rank: dict[CredenceTier, int] = Field(
        default_factory=lambda: {
            CredenceTier.FIRM_AUTHORITATIVE: 4,
            CredenceTier.VERIFIED: 3,
            CredenceTier.MODEL_INFERRED: 2,
            CredenceTier.UNVERIFIED: 1,
        }
    )
    load_bearing_minimum: CredenceTier = CredenceTier.VERIFIED


class RetrievalCandidate(SolomonModel):
    item: KnowledgeItem
    relevance: float
    centrality: float = 0.0


class CredenceAuditEntry(SolomonModel):
    item_id: str
    action: CredenceAction
    from_tier: CredenceTier | None
    to_tier: CredenceTier
    by: str
    reason: str
    recorded_at: datetime = Field(default_factory=now_utc)

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        from solomon.currency.models import _ensure_aware_utc

        return _ensure_aware_utc(value)


class LoadBearingDecision(SolomonModel):
    allowed: bool
    item_id: str
    reasons: list[str]


class PromptContext(SolomonModel):
    factual_blocks: list[str]
    ignored_instruction_item_ids: list[str]

    @property
    def text(self) -> str:
        return "\n\n".join(self.factual_blocks)


class CredenceLedger:
    def __init__(self, *, policy: CredencePolicy | None = None) -> None:
        self.policy = policy or CredencePolicy()
        self.entries: list[CredenceAuditEntry] = []

    def assign_on_ingest(self, item: KnowledgeItem, *, by: str = "system") -> KnowledgeItem:
        tier = self.policy.source_tiers.get(item.provenance.source_kind, CredenceTier.UNVERIFIED)
        verified_state = VerifiedState.NEEDS_REVIEW if tier is CredenceTier.MODEL_INFERRED else item.verified_state
        updated = item.model_copy(update={"credence_tier": tier, "verified_state": verified_state})
        self.entries.append(
            CredenceAuditEntry(
                item_id=item.id,
                action=CredenceAction.ASSIGN,
                from_tier=item.credence_tier,
                to_tier=tier,
                by=by,
                reason=f"source kind {item.provenance.source_kind.value}",
            )
        )
        return updated

    def change_tier(self, item: KnowledgeItem, *, to_tier: CredenceTier, by: str, reason: str) -> KnowledgeItem:
        action = (
            CredenceAction.PROMOTE
            if self.policy.tier_rank[to_tier] > self.policy.tier_rank[item.credence_tier]
            else CredenceAction.DEMOTE
        )
        updated = item.model_copy(update={"credence_tier": to_tier})
        self.entries.append(
            CredenceAuditEntry(
                item_id=item.id,
                action=action,
                from_tier=item.credence_tier,
                to_tier=to_tier,
                by=by,
                reason=reason,
            )
        )
        return updated

    def rank(self, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.relevance,
                self.policy.tier_rank[candidate.item.credence_tier],
                candidate.centrality,
                candidate.item.ingested_at,
            ),
            reverse=True,
        )

    def load_bearing_decision(self, item: KnowledgeItem) -> LoadBearingDecision:
        reasons: list[str] = []
        evaluation = evaluate_currency(item)
        if item.content_role is KnowledgeContentRole.INSTRUCTION:
            reasons.append("stored content is instruction-role and cannot support load-bearing output")
        if evaluation.currency_state is not CurrencyState.LIVE:
            reasons.append(f"currency state is {evaluation.currency_state.value}")
        if self.policy.tier_rank[item.credence_tier] < self.policy.tier_rank[self.policy.load_bearing_minimum]:
            reasons.append(
                f"credence tier {item.credence_tier.value} is below {self.policy.load_bearing_minimum.value}"
            )
        return LoadBearingDecision(allowed=not reasons, item_id=item.id, reasons=reasons)


def assemble_factual_context(items: list[KnowledgeItem]) -> PromptContext:
    factual_blocks: list[str] = []
    ignored_instruction_item_ids: list[str] = []
    for item in items:
        if item.content_role is KnowledgeContentRole.INSTRUCTION:
            ignored_instruction_item_ids.append(item.id)
            continue
        factual_blocks.append(
            f"[{item.id}] role={item.content_role.value}; credence={item.credence_tier.value}; "
            f"currency={item.currency_state.value}\n{item.content}"
        )
    return PromptContext(factual_blocks=factual_blocks, ignored_instruction_item_ids=ignored_instruction_item_ids)
