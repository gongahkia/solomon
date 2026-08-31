# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from time import monotonic, perf_counter
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import (
    Counter as PrometheusCounter,
)

from solomon.currency.models import CurrencyState, now_utc
from solomon.operations.models import OperationStatus
from solomon.sources.models import SourceSyncRunState
from solomon.store.sqlite import SQLiteKnowledgeStore
from solomon.workflow.models import ReviewTaskState

if TYPE_CHECKING:
    from solomon.api.service import SolomonService


class SolomonMetrics:
    """Low-cardinality Prometheus instrumentation for Solomon runtime operations."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self._audit_health: dict[str, tuple[float, bool]] = {}
        self.http_requests = PrometheusCounter(
            "solomon_http_requests_total",
            "Completed Solomon HTTP requests.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "solomon_http_request_duration_seconds",
            "Completed Solomon HTTP request duration.",
            ("method", "route"),
            registry=self.registry,
        )
        self.retrieval_requests = PrometheusCounter(
            "solomon_retrieval_requests_total",
            "Retrieval executions.",
            registry=self.registry,
        )
        self.retrieval_candidates = PrometheusCounter(
            "solomon_retrieval_candidates_total",
            "Retrieval candidates before currency filtering.",
            registry=self.registry,
        )
        self.retrieval_results = PrometheusCounter(
            "solomon_retrieval_results_total",
            "Retrieval results returned after filtering and context budget selection.",
            registry=self.registry,
        )
        self.context_withheld = PrometheusCounter(
            "solomon_retrieval_context_withheld_total",
            "Retrieval candidates withheld by currency state.",
            ("currency_state",),
            registry=self.registry,
        )
        self.health = Gauge(
            "solomon_health",
            "Current local component health; 1 is healthy.",
            ("component",),
            registry=self.registry,
        )
        self.queue_depth = Gauge(
            "solomon_queue_depth",
            "Current durable queue depth.",
            ("queue",),
            registry=self.registry,
        )
        self.review_tasks = Gauge(
            "solomon_review_tasks",
            "Current review task count by state.",
            ("state",),
            registry=self.registry,
        )
        self.source_sync = Gauge(
            "solomon_source_sync_sources",
            "Current document sources by latest synchronization state.",
            ("state",),
            registry=self.registry,
        )
        self.operation_states = Gauge(
            "solomon_operation_state",
            "Current durable operations by lifecycle state.",
            ("state",),
            registry=self.registry,
        )
        self.operation_oldest_pending_seconds = Gauge(
            "solomon_operation_oldest_pending_seconds",
            "Age of the oldest queued, claimed, or retrying durable operation.",
            registry=self.registry,
        )
        self.consistency_signals = Gauge(
            "solomon_consistency_signal",
            "Bounded consistency inspection and repair signals since service startup.",
            ("signal",),
            registry=self.registry,
        )
        self.scrape_duration = Histogram(
            "solomon_metrics_scrape_duration_seconds",
            "Time spent refreshing Solomon Prometheus metrics.",
            registry=self.registry,
        )

    def attach(self, service: SolomonService) -> None:
        service.retrieval.metrics_observer = self

    def observe_http(self, *, method: str, path: str, status: int, elapsed_seconds: float) -> None:
        route = _route_label(path)
        self.http_requests.labels(method=method, route=route, status=str(status)).inc()
        self.http_duration.labels(method=method, route=route).observe(elapsed_seconds)

    def observe_retrieval(
        self,
        *,
        candidates: int,
        returned: int,
        withheld_by_currency_state: Mapping[CurrencyState, int],
    ) -> None:
        self.retrieval_requests.inc()
        self.retrieval_candidates.inc(candidates)
        self.retrieval_results.inc(returned)
        for state, count in withheld_by_currency_state.items():
            self.context_withheld.labels(currency_state=state.value).inc(count)

    def render(self, services: Iterable[SolomonService]) -> tuple[bytes, str]:
        started_at = perf_counter()
        self._refresh(list(services))
        self.scrape_duration.observe(perf_counter() - started_at)
        return generate_latest(self.registry), CONTENT_TYPE_LATEST

    def _refresh(self, services: list[SolomonService]) -> None:
        audit_healthy = True
        queue_counts: Counter[str] = Counter()
        review_counts: Counter[str] = Counter()
        sync_counts: Counter[str] = Counter()
        operation_counts: Counter[str] = Counter()
        consistency_counts: Counter[str] = Counter()
        oldest_pending_at = None
        for service in services:
            audit_healthy = self._audit_is_healthy(service) and audit_healthy
            if isinstance(service.store, SQLiteKnowledgeStore):
                queue_counts["knowledge_outbox"] += service.store.outbox_queue_depth()
            poll_counts = service.authority_sources.poll_queue_depths()
            queue_counts["authority_poll"] += poll_counts["pending"]
            queue_counts["authority_poll_dead_letter"] += poll_counts["dead_letter"]
            review_counts.update(service.workflow_store.review_task_state_counts())
            sync_counts.update(service.document_store.sync_source_state_counts())
            consistency_counts.update(service.consistency_signals)
            for operation in service.operation_store.list(limit=10_000):
                operation_counts[operation.status.value] += 1
                if operation.status in {OperationStatus.QUEUED, OperationStatus.CLAIMED, OperationStatus.RETRYING}:
                    if oldest_pending_at is None or operation.created_at < oldest_pending_at:
                        oldest_pending_at = operation.created_at
        self.health.labels(component="audit_journal").set(float(audit_healthy))
        for queue in ("knowledge_outbox", "authority_poll", "authority_poll_dead_letter"):
            self.queue_depth.labels(queue=queue).set(queue_counts[queue])
        for state in ReviewTaskState:
            self.review_tasks.labels(state=state.value).set(review_counts[state.value])
        for state in (*SourceSyncRunState, "never"):
            label = state.value if isinstance(state, SourceSyncRunState) else state
            self.source_sync.labels(state=label).set(sync_counts[label])
        for operation_state in OperationStatus:
            self.operation_states.labels(state=operation_state.value).set(operation_counts[operation_state.value])
        oldest_age = 0.0 if oldest_pending_at is None else max(0.0, (now_utc() - oldest_pending_at).total_seconds())
        self.operation_oldest_pending_seconds.set(oldest_age)
        for signal in ("checks", "findings", "repairs_planned", "repairs_applied", "repairs_refused"):
            self.consistency_signals.labels(signal=signal).set(consistency_counts[signal])

    def _audit_is_healthy(self, service: SolomonService) -> bool:
        key = str(service.audit.path)
        now = monotonic()
        cached = self._audit_health.get(key)
        if cached is not None and now - cached[0] < 30.0:
            return cached[1]
        healthy = service.audit.verify().ok
        self._audit_health[key] = (now, healthy)
        return healthy


def request_started() -> float:
    return perf_counter()


def _route_label(path: str) -> str:
    if path in {"/health", "/ready", "/metrics"}:
        return path
    for prefix in ("/sources", "/source-documents", "/candidate-claims"):
        if path.startswith(prefix):
            return "/sources/*"
    for prefix in ("/authority-polls", "/authority-events", "/authorities"):
        if path.startswith(prefix):
            return "/authorities/*"
    for prefix in ("/review-tasks", "/verification"):
        if path.startswith(prefix):
            return "/review/*"
    for prefix in ("/dependencies", "/recall", "/answer", "/currency", "/timeline"):
        if path.startswith(prefix):
            return "/retrieval/*"
    return "/other"


__all__ = ["SolomonMetrics", "request_started"]
