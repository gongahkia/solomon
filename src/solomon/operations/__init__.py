# SPDX-License-Identifier: Apache-2.0

"""Durable, bounded operation records for cross-persistence projections."""

from solomon.operations.execution import OperationRequiresIntervention, OperationRunner
from solomon.operations.failure_injection import InjectedOperationFailure, OperationFailureInjector
from solomon.operations.models import (
    OperationHistoryEntry,
    OperationPhase,
    OperationRecord,
    OperationScope,
    OperationStatus,
    OperationType,
)
from solomon.operations.postgres import PostgresOperationStore
from solomon.operations.store import SQLiteOperationStore

__all__ = [
    "OperationHistoryEntry",
    "OperationFailureInjector",
    "OperationPhase",
    "OperationRecord",
    "OperationRequiresIntervention",
    "OperationRunner",
    "OperationScope",
    "OperationStatus",
    "OperationType",
    "InjectedOperationFailure",
    "PostgresOperationStore",
    "SQLiteOperationStore",
]
