from datetime import UTC, datetime, timedelta, timezone

import pytest

from stonks_cli.vnext.scheduled_run_deduplication import InMemoryScheduledRunDeduplicator, ScheduledRunKey


def test_scheduled_run_deduplicator_claims_each_utc_job_slot_once():
    deduplicator = InMemoryScheduledRunDeduplicator()
    original = ScheduledRunKey("vnext.daily_operator_report", datetime(2026, 7, 14, 17, 30, tzinfo=UTC))
    same_slot = ScheduledRunKey(
        "vnext.daily_operator_report",
        datetime(2026, 7, 15, 1, 30, tzinfo=timezone(timedelta(hours=8))),
    )

    assert deduplicator.claim(original) is True
    assert deduplicator.claim(same_slot) is False


def test_scheduled_run_deduplicator_fails_closed_for_malformed_keys():
    with pytest.raises(ValueError, match="job ID"):
        ScheduledRunKey("", datetime(2026, 7, 14, 17, 30, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        ScheduledRunKey("vnext.daily_operator_report", datetime(2026, 7, 14, 17, 30))
    with pytest.raises(TypeError, match="key"):
        InMemoryScheduledRunDeduplicator().claim(object())  # type: ignore[arg-type]
