# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

from solomon.contracts import (
    DOMAIN_CONTRACT_VERSION,
    AdapterHealth,
    AuthorityObservation,
    AuthoritySource,
    AuthoritySourceAdapter,
    AuthoritySourceKind,
    DiscoveredDocument,
    DocumentSourceAdapter,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    ReviewDispatch,
    ReviewDispatcher,
    ReviewDispatchResult,
    SyncCheckpoint,
    WebhookDelivery,
    WebhookDeliveryResult,
    WebhookDispatcher,
    WebhookEvent,
)
from solomon.sources.models import DocumentSource, DocumentSourceKind
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskPriority


class StubDocumentAdapter:
    kind = DocumentSourceKind.FILESYSTEM

    def health(self, source: DocumentSource) -> AdapterHealth:
        _ = source
        return AdapterHealth(healthy=True)

    def discover(
        self,
        source: DocumentSource,
        checkpoint: SyncCheckpoint | None,
    ) -> tuple[list[DiscoveredDocument], SyncCheckpoint | None]:
        _ = checkpoint
        return [
            DiscoveredDocument(external_id="memo-1", filename="memo.txt", content_ref="file:///memo.txt")
        ], SyncCheckpoint(
            source_id=source.id,
            cursor="next",
        )


class StubAuthorityAdapter:
    kind = AuthoritySourceKind.FEED

    def health(self, source: AuthoritySource) -> AdapterHealth:
        _ = source
        return AdapterHealth(healthy=True)

    def poll(
        self,
        source: AuthoritySource,
        checkpoint: SyncCheckpoint | None,
    ) -> tuple[list[AuthorityChangeEvent], SyncCheckpoint | None]:
        _ = source, checkpoint
        return [], None

    def checkpoint(self, source: AuthoritySource) -> SyncCheckpoint | None:
        return SyncCheckpoint(source_id=source.id, cursor="v2")

    def replay(self, source: AuthoritySource, checkpoint: SyncCheckpoint) -> list[AuthorityChangeEvent]:
        return [
            AuthorityChangeEvent(
                source_id=source.id,
                idempotency_key=f"{checkpoint.cursor}:regulation-r-12",
                authority_id="regulation-r-12",
                new_version="v2",
                changed_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
            )
        ]


class UnhealthyAuthorityAdapter(StubAuthorityAdapter):
    def health(self, source: AuthoritySource) -> AdapterHealth:
        _ = source
        return AdapterHealth(healthy=False, detail="upstream unavailable")


class StubEmbeddingProvider:
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(model=request.model, vectors=[[0.25] for _ in request.texts])


class StubReviewDispatcher:
    def dispatch(self, dispatch: ReviewDispatch) -> ReviewDispatchResult:
        _ = dispatch
        return ReviewDispatchResult(delivery_id="delivery-1")


class StubWebhookDispatcher:
    def deliver(self, delivery: WebhookDelivery) -> WebhookDeliveryResult:
        _ = delivery
        return WebhookDeliveryResult(delivery_id="delivery-1", status_code=202)


def test_versioned_contract_models_normalize_timestamps_and_carry_contract_version():
    observation = AuthorityObservation(
        authority_id="sg-reg-1",
        version="v2",
        effective_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        diff={"changed": ["section-12"]},
    )
    event = WebhookEvent(event_type="authority.changed", event_id="event-1")

    assert observation.schema_version == DOMAIN_CONTRACT_VERSION
    assert observation.effective_at.tzinfo is timezone.utc
    assert event.schema_version == DOMAIN_CONTRACT_VERSION


def test_contract_protocols_accept_typed_adapter_implementations():
    source = DocumentSource(
        id="source-1",
        name="files",
        kind=DocumentSourceKind.FILESYSTEM,
        root_ref="/knowledge",
    )
    authority = AuthoritySource(
        id="authority-1",
        name="official",
        kind=AuthoritySourceKind.FEED,
        root_ref="feed://official",
    )
    task = ReviewTask(
        event_id="event-1",
        item_id="item-1",
        priority=ReviewTaskPriority.HIGH,
        reason="authority changed",
    )

    document_adapter = StubDocumentAdapter()
    authority_adapter = StubAuthorityAdapter()
    embedding_provider = StubEmbeddingProvider()
    review_dispatcher = StubReviewDispatcher()
    webhook_dispatcher = StubWebhookDispatcher()

    assert isinstance(document_adapter, DocumentSourceAdapter)
    assert isinstance(authority_adapter, AuthoritySourceAdapter)
    assert isinstance(embedding_provider, EmbeddingProvider)
    assert isinstance(review_dispatcher, ReviewDispatcher)
    assert isinstance(webhook_dispatcher, WebhookDispatcher)
    discovered, checkpoint = document_adapter.discover(source, None)
    assert discovered[0].external_id == "memo-1"
    assert checkpoint is not None
    assert authority_adapter.health(authority).healthy is True
    authority_checkpoint = authority_adapter.checkpoint(authority)
    assert authority_checkpoint is not None
    replayed = authority_adapter.replay(authority, authority_checkpoint)
    assert replayed[0].idempotency_key == "v2:regulation-r-12"
    assert authority_adapter.replay(authority, authority_checkpoint)[0].idempotency_key == replayed[0].idempotency_key
    assert UnhealthyAuthorityAdapter().health(authority).healthy is False
    assert embedding_provider.embed(EmbeddingRequest(model="local", texts=["text"])).vectors == [[0.25]]
    dispatch = ReviewDispatch(task=task, destination="queue://reviews", idempotency_key="task-1")
    assert review_dispatcher.dispatch(dispatch).delivery_id == "delivery-1"
    delivery = WebhookDelivery(
        event=WebhookEvent(event_type="review.created", event_id="event-1"),
        target_url="https://example.test",
        idempotency_key="event-1",
    )
    assert webhook_dispatcher.deliver(delivery).status_code == 202
