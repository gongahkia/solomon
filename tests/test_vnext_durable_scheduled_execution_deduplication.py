from datetime import UTC, datetime, timedelta, timezone

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.durable_scheduled_execution_deduplication import (
    DurableScheduledExecutionDeduplicator,
    ScheduledExecutionSlot,
)


def test_durable_scheduled_execution_deduplication_blocks_duplicate_slots_across_instances(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "scheduler.sqlite3")
    first = DurableScheduledExecutionDeduplicator(factory)
    second = DurableScheduledExecutionDeduplicator(factory)
    original = ScheduledExecutionSlot("vnext.daily_operator_report", datetime(2026, 7, 14, 17, 30, tzinfo=UTC))
    same_slot = ScheduledExecutionSlot(
        "vnext.daily_operator_report",
        datetime(2026, 7, 15, 1, 30, tzinfo=timezone(timedelta(hours=8))),
    )

    assert first.claim(original) is True
    assert second.claim(same_slot) is False
    assert second.claim(ScheduledExecutionSlot("vnext.daily_operator_report", datetime(2026, 7, 15, 17, 30, tzinfo=UTC))) is True


def test_durable_scheduled_execution_deduplication_fails_closed_for_malformed_slots(tmp_path):
    deduplicator = DurableScheduledExecutionDeduplicator(SQLiteConnectionFactory(tmp_path / "scheduler.sqlite3"))
    with pytest.raises(ValueError, match="job ID"):
        ScheduledExecutionSlot("daily report", datetime(2026, 7, 14, 17, 30, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        ScheduledExecutionSlot("vnext.daily_operator_report", datetime(2026, 7, 14, 17, 30))
    with pytest.raises(TypeError, match="slot"):
        deduplicator.claim(object())  # type: ignore[arg-type]
