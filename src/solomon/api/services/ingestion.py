# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from solomon.api.service_models import (
    AffirmRequest,
    AffirmResponse,
    ContestRequest,
    ContestResponse,
    IngestRequest,
    PinRequest,
)
from solomon.api.services.base import ServiceDelegate
from solomon.api.services.common import digest
from solomon.audit.journal import AuditAttribution
from solomon.currency.models import (
    CredenceTier,
    CurrencyState,
    KnowledgeContentRole,
    KnowledgeItem,
    Provenance,
    SourceKind,
    VerifiedState,
    new_uuid7,
)
from solomon.errors import BadRequestError, PolicyRefusalError
from solomon.graph.propagation import CurrencyPropagator
from solomon.store.hardening import harden_stored_content


class IngestionService(ServiceDelegate):
    def ingest(self, request: IngestRequest) -> KnowledgeItem:
        hardened = harden_stored_content(request.content)
        metadata: dict[str, Any] = {"stored_content_hardening": hardened.findings} if hardened.findings else {}
        if request.conclusion:
            metadata["conclusion"] = request.conclusion
        if request.conclusion_polarity is not None:
            metadata["conclusion_polarity"] = request.conclusion_polarity.value
        if request.source_document_id is not None:
            metadata["source_document"] = {
                "id": request.source_document_id,
                "version": request.source_document_version,
                "previous_document_id": request.previous_source_document_id,
                "span_start": request.source_document_span_start,
                "span_end": request.source_document_span_end,
            }
        item = KnowledgeItem(
            kind=request.kind,
            content=hardened.content,
            content_role=(
                KnowledgeContentRole.INSTRUCTION
                if hardened.content_role is KnowledgeContentRole.INSTRUCTION
                else request.content_role or hardened.content_role
            ),
            provenance=Provenance(
                source_kind=request.source_kind,
                source_ref=request.source_ref,
                author=request.author,
                matter_id=request.matter_id,
            ),
            valid_from=request.valid_from or datetime.now().astimezone(),
            ingested_at=request.ingested_at or datetime.now().astimezone(),
            matter_id=request.matter_id,
            client_id=request.client_id,
            metadata=metadata,
        )
        item, _review = self.boundary.review_for_ingest(item)
        credence_entry_start = len(self.credence.entries)
        item = self.credence.assign_on_ingest(item)
        self._persist_credence_entries(start=credence_entry_start)
        item = self._seed_verification_from_source(item)
        item = self.index.upsert_item(item)
        self.store.write_item(item)
        if hardened.findings:
            self.audit.append(
                "stored_content_hardened",
                {
                    "item_id": item.id,
                    "decision": item.content_role.value,
                    "findings": hardened.findings,
                },
                attribution=AuditAttribution(
                    actor_id=request.author or f"source:{request.source_kind.value}",
                    correlation_id=f"knowledge_item:{item.id}",
                ),
            )
        self._create_dependency_suggestions(item)
        return item

    def contest(self, item_id: str, request: ContestRequest) -> ContestResponse:
        timestamp = request.contested_at or datetime.now(timezone.utc)
        item = self._get_item(item_id)
        contest_id = new_uuid7()
        correction = self._create_contest_correction(item, request, contest_id=contest_id, timestamp=timestamp)
        contests = list(item.metadata.get("contests", []))
        contests.append(
            {
                "contest_id": contest_id,
                "lawyer_id": request.lawyer_id,
                "reason": request.reason,
                "actor_tier": request.actor_tier.value,
                "contested_at": timestamp.isoformat(),
                "proposed_correction_item_id": correction.id if correction is not None else None,
                "status": "pending_review",
            }
        )
        staleness_reasons = list(item.metadata.get("staleness_reasons", []))
        staleness_reasons.append(
            {
                "dependency_id": item.id,
                "changed_at": timestamp.isoformat(),
                "reason": f"contest by {request.lawyer_id}: {request.reason}",
                "edge_id": None,
            }
        )
        contested = item.model_copy(
            update={
                "currency_state": CurrencyState.STALE_PENDING_REVERIFICATION,
                "verified_state": VerifiedState.NEEDS_REVIEW,
                "credence_tier": CredenceTier.UNVERIFIED,
                "metadata": {
                    **item.metadata,
                    "contests": contests,
                    "staleness_reasons": staleness_reasons,
                    "contested": True,
                },
            }
        )
        self.store.update_item(contested, event_type="knowledge_item_contested", occurred_at=timestamp)
        self.index.upsert_item(contested)
        self.currency_cache.invalidate({item_id})
        impact = CurrencyPropagator(graph=self.graph, store=self.store).propagate_dependency_change(
            item_id,
            changed_at=timestamp,
            reason=f"contest on {item_id} requires dependent re-verification",
        )
        self.currency_cache.invalidate(set(impact.stale_item_ids))
        self.audit.log_impact(impact)
        self.audit.append(
            "contest",
            {
                "contest_id": contest_id,
                "item_id": item_id,
                "lawyer_id": request.lawyer_id,
                "actor_tier": request.actor_tier.value,
                "reason_sha256": digest(request.reason),
                "proposed_correction_item_id": correction.id if correction is not None else None,
                "proposed_correction_sha256": (
                    digest(request.proposed_correction) if request.proposed_correction else None
                ),
            },
            occurred_at=timestamp,
        )
        return ContestResponse(item=contested, correction_item=correction, impact=impact.model_dump(mode="json"))

    def affirm(self, item_id: str, request: AffirmRequest) -> AffirmResponse:
        if request.actor_tier is not CredenceTier.FIRM_AUTHORITATIVE:
            raise PolicyRefusalError("only FirmAuthoritative actors can affirm contested knowledge")
        timestamp = request.affirmed_at or datetime.now(timezone.utc)
        item = self._get_item(item_id)
        if request.correction_item_id is not None:
            correction = self._get_item(request.correction_item_id)
            if correction.metadata.get("proposed_correction_for") != item_id:
                raise BadRequestError("correction item is not proposed for this item")
            successor_metadata = {
                **correction.metadata,
                "quarantined": False,
                "affirmed_by": request.lawyer_id,
                "affirmed_at": timestamp.isoformat(),
                "contest_status": "affirmed",
            }
            successor = correction.model_copy(
                update={
                    "currency_state": CurrencyState.LIVE,
                    "verified_state": VerifiedState.VERIFIED,
                    "last_verified_at": timestamp,
                    "verified_by": request.lawyer_id,
                    "credence_tier": CredenceTier.FIRM_AUTHORITATIVE,
                    "metadata": successor_metadata,
                }
            )
            closed, written_successor = self.store.supersede(item_id, successor, superseded_at=timestamp)
            self.index.upsert_item(closed)
            self.index.upsert_item(written_successor)
            self.currency_cache.invalidate({item_id, written_successor.id})
            self.audit.append(
                "affirm",
                {
                    "item_id": item_id,
                    "lawyer_id": request.lawyer_id,
                    "correction_item_id": written_successor.id,
                    "superseded": True,
                },
                occurred_at=timestamp,
            )
            return AffirmResponse(item=closed, correction_item=written_successor, superseded=True)

        metadata = dict(item.metadata)
        metadata["affirmed_by"] = request.lawyer_id
        metadata["affirmed_at"] = timestamp.isoformat()
        metadata["contest_status"] = "affirmed"
        metadata.pop("staleness_reasons", None)
        affirmed = item.model_copy(
            update={
                "currency_state": CurrencyState.LIVE,
                "verified_state": VerifiedState.VERIFIED,
                "last_verified_at": timestamp,
                "verified_by": request.lawyer_id,
                "credence_tier": CredenceTier.FIRM_AUTHORITATIVE,
                "metadata": metadata,
            }
        )
        self.store.update_item(affirmed, event_type="knowledge_item_affirmed", occurred_at=timestamp)
        self.index.upsert_item(affirmed)
        self.currency_cache.invalidate({item_id})
        self.audit.append(
            "affirm",
            {"item_id": item_id, "lawyer_id": request.lawyer_id, "superseded": False},
            occurred_at=timestamp,
        )
        return AffirmResponse(item=affirmed)

    def pin(self, item_id: str, request: PinRequest) -> KnowledgeItem:
        if request.actor_tier is not CredenceTier.FIRM_AUTHORITATIVE:
            raise PolicyRefusalError("only FirmAuthoritative actors can pin knowledge")
        timestamp = request.pinned_at or datetime.now(timezone.utc)
        item = self._get_item(item_id)
        pinned = item.model_copy(
            update={
                "credence_tier": CredenceTier.FIRM_AUTHORITATIVE,
                "metadata": {
                    **item.metadata,
                    "credence_floor": CredenceTier.FIRM_AUTHORITATIVE.value,
                    "pinned_by": request.lawyer_id,
                    "pinned_at": timestamp.isoformat(),
                    "pin_reason": request.reason,
                },
            }
        )
        self.store.update_item(pinned, event_type="knowledge_item_pinned", occurred_at=timestamp)
        self.index.upsert_item(pinned)
        self.currency_cache.invalidate({item_id})
        self.audit.append(
            "pin",
            {
                "item_id": item_id,
                "lawyer_id": request.lawyer_id,
                "reason_sha256": digest(request.reason),
                "credence_floor": CredenceTier.FIRM_AUTHORITATIVE.value,
            },
            occurred_at=timestamp,
        )
        return pinned

    def _create_contest_correction(
        self,
        item: KnowledgeItem,
        request: ContestRequest,
        *,
        contest_id: str,
        timestamp: datetime,
    ) -> KnowledgeItem | None:
        if request.proposed_correction is None:
            return None
        correction = KnowledgeItem(
            kind=item.kind,
            content=request.proposed_correction,
            content_role=item.content_role,
            provenance=Provenance(
                source_kind=(
                    SourceKind.MODEL if request.actor_tier is CredenceTier.MODEL_INFERRED else SourceKind.ASSOCIATE
                ),
                source_ref=f"contest:{contest_id}",
                author=request.lawyer_id,
                matter_id=item.matter_id,
            ),
            valid_from=timestamp,
            ingested_at=timestamp,
            matter_id=item.matter_id,
            client_id=item.client_id,
            currency_state=CurrencyState.STALE_PENDING_REVERIFICATION,
            verified_state=VerifiedState.NEEDS_REVIEW,
            credence_tier=CredenceTier.UNVERIFIED,
            metadata={
                "proposed_correction_for": item.id,
                "contest_id": contest_id,
                "quarantined": True,
                "contest_status": "pending_review",
            },
        )
        correction, _review = self.boundary.review_for_ingest(correction)
        correction = self.index.upsert_item(correction)
        self.store.write_item(correction)
        return correction

    def _seed_verification_from_source(self, item: KnowledgeItem) -> KnowledgeItem:
        if item.credence_tier not in {CredenceTier.FIRM_AUTHORITATIVE, CredenceTier.VERIFIED}:
            return item
        return item.model_copy(
            update={
                "verified_state": VerifiedState.VERIFIED,
                "last_verified_at": item.ingested_at,
                "verified_by": item.provenance.author or f"source:{item.provenance.source_kind.value}",
            }
        )
