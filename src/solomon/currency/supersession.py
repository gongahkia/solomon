# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem
from solomon.store.types import KnowledgeStoreProtocol


class SupersessionProposal(SolomonModel):
    predecessor_id: str
    successor_id: str
    topic: str
    jurisdiction: str
    reason: str
    requires_human_confirmation: bool = True


def propose_supersession(newer: KnowledgeItem, candidates: list[KnowledgeItem]) -> list[SupersessionProposal]:
    topic = str(newer.metadata.get("topic", "")).strip()
    jurisdiction = str(newer.metadata.get("jurisdiction", "")).strip()
    if not topic or not jurisdiction:
        return []
    proposals: list[SupersessionProposal] = []
    for candidate in candidates:
        if candidate.id == newer.id:
            continue
        if candidate.ingested_at >= newer.ingested_at:
            continue
        same_topic = str(candidate.metadata.get("topic", "")).strip() == topic
        same_jurisdiction = str(candidate.metadata.get("jurisdiction", "")).strip() == jurisdiction
        contradiction = bool(newer.metadata.get("contradicts") == candidate.id or candidate.content != newer.content)
        if same_topic and same_jurisdiction and contradiction:
            proposals.append(
                SupersessionProposal(
                    predecessor_id=candidate.id,
                    successor_id=newer.id,
                    topic=topic,
                    jurisdiction=jurisdiction,
                    reason="newer item on same topic/jurisdiction may supersede older item",
                )
            )
    return proposals


def confirm_supersession(
    store: KnowledgeStoreProtocol,
    proposal: SupersessionProposal,
) -> tuple[KnowledgeItem, KnowledgeItem]:
    successor = store.get_item(proposal.successor_id)
    return store.supersede(proposal.predecessor_id, successor, superseded_at=successor.valid_from)
