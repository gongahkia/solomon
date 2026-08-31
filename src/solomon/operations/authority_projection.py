# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from solomon.audit.journal import AuditAttribution
from solomon.currency.engine import register_authority_change
from solomon.currency.verification import VerificationLifecycleState, latest_verification_event
from solomon.graph.propagation import CurrencyPropagator
from solomon.operations.execution import OperationRequiresIntervention
from solomon.operations.failure_injection import OperationFailureInjector
from solomon.operations.models import OperationPhase, OperationRecord, OperationStatus, OperationType


class AuthorityChangeProjection:
    """Idempotently propagate one durable authority change using the operation ID as the currency change ID."""

    def __init__(
        self,
        *,
        authority_service: Any,
        operation_store: Any,
        failure_injector: OperationFailureInjector | None = None,
    ) -> None:
        self._authority_service = authority_service
        self._operation_store = operation_store
        self._failure_injector = failure_injector or OperationFailureInjector()

    def apply(self, operation: OperationRecord, worker_id: str) -> OperationRecord:
        if operation.operation_type is not OperationType.AUTHORITY_CHANGE_PROPAGATION:
            raise OperationRequiresIntervention("operation type is not an authority change")
        if operation.status is not OperationStatus.CLAIMED or operation.target_resource_id is None:
            raise OperationRequiresIntervention("authority change is incomplete or not claimed")
        new_version = operation.payload.get("new_version")
        changed_at = operation.payload.get("changed_at")
        change_id = operation.payload.get("change_id")
        if not isinstance(new_version, str) or not isinstance(changed_at, str):
            raise OperationRequiresIntervention("authority change payload is incomplete")
        try:
            timestamp = datetime.fromisoformat(changed_at)
        except ValueError as exc:
            raise OperationRequiresIntervention("authority change timestamp is invalid") from exc
        currency_change_id = change_id if isinstance(change_id, str) else operation.id

        current = operation
        impact = None
        if current.last_successful_checkpoint not in {OperationPhase.CURRENCY, OperationPhase.AUDIT}:
            self._failure_injector.hit("during_currency_propagation")
            impact = register_authority_change(
                authority_id=operation.target_resource_id,
                new_version=new_version,
                changed_at=timestamp,
                graph=self._authority_service.graph,
                store=self._authority_service.store,
                change_id=currency_change_id,
            )
            self._authority_service.currency_cache.invalidate(set(impact.stale_item_ids))
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.CURRENCY,
                result_entity_id=operation.target_resource_id,
            )
        if current.last_successful_checkpoint is not OperationPhase.AUDIT:
            impact = impact or self._impact(operation.target_resource_id, change_id=currency_change_id)
            self._failure_injector.hit("after_currency_before_audit")
            for item_id in impact.stale_item_ids:
                item = self._authority_service._get_item(item_id)
                event = latest_verification_event(item)
                if event is not None and event.state is VerificationLifecycleState.REQUESTED:
                    self._authority_service.audit.append_idempotent(
                        "verification_lifecycle_event",
                        event.model_dump(mode="json"),
                        operation_id=f"{current.id}:currency:{item_id}",
                        occurred_at=event.occurred_at,
                        attribution=AuditAttribution(
                            actor_id="system:authority-monitor",
                            correlation_id=operation.correlation_id,
                        ),
                    )
            impact_entry = self._authority_service.audit.append_idempotent(
                "impact",
                impact.model_dump(mode="json"),
                operation_id=f"{current.id}:impact",
                attribution=AuditAttribution(
                    actor_id="system:authority-monitor",
                    correlation_id=operation.correlation_id,
                ),
            )
            current = self._operation_store.checkpoint(
                current.id,
                worker_id=worker_id,
                phase=OperationPhase.AUDIT,
                result_entity_id=operation.target_resource_id,
                audit_entry_hash=impact_entry.entry_hash,
            )
        return cast(
            OperationRecord,
            self._operation_store.complete(
                current.id,
                worker_id=worker_id,
                result_entity_id=operation.target_resource_id,
            ),
        )

    def _impact(self, authority_id: str, *, change_id: str) -> Any:
        impact = CurrencyPropagator(
            graph=self._authority_service.graph,
            store=self._authority_service.store,
        ).impact_query(authority_id)
        return impact.model_copy(update={"change_id": change_id})


__all__ = ["AuthorityChangeProjection"]
