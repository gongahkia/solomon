from datetime import UTC, datetime
from uuid import UUID

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.durable_task_queue import DurableTaskQueue, create_durable_task
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.foundation import FrozenUTCClock


def test_durable_task_queue_persists_pending_tasks_and_peeks_in_enqueue_order(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "queue.sqlite3")
    queue = DurableTaskQueue(factory)
    first = create_durable_task(
        "operator.daily_report",
        {"report_id": "daily-1"},
        FrozenUTCClock(datetime(2026, 7, 14, 2, tzinfo=UTC)),
        task_id=UUID("00000000-0000-4000-8000-000000000001"),
    )
    second = create_durable_task(
        "operator.weekly_report",
        {"report_id": "weekly-1"},
        FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        task_id=UUID("00000000-0000-4000-8000-000000000002"),
    )

    queue.enqueue(second)
    queue.enqueue(first)

    assert DurableTaskQueue(factory).peek() == first


def test_durable_task_queue_fails_closed_for_sensitive_payloads_or_duplicate_tasks(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "queue.sqlite3")
    queue = DurableTaskQueue(factory)
    task = create_durable_task(
        "operator.daily_report",
        {"report_id": "daily-1"},
        FrozenUTCClock(datetime(2026, 7, 14, 2, tzinfo=UTC)),
        task_id=UUID("00000000-0000-4000-8000-000000000001"),
    )
    with pytest.raises(ValueError, match="sensitive"):
        create_durable_task("operator.daily_report", {"bot_token": "secret"}, FrozenUTCClock(datetime(2026, 7, 14, 2, tzinfo=UTC)))
    queue.enqueue(task)
    with pytest.raises(VNextInvariantError, match="already enqueued"):
        queue.enqueue(task)
