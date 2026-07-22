from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stonks_cli import operator
from stonks_cli.operator import (
    ScheduleAction,
    ScheduleCadence,
    ScheduleDefinition,
    ScheduledJob,
    ScheduleJobKind,
    default_scheduler_plan,
    linux_schedule_status,
    notify_telegram,
    render_schedule,
    render_systemd_units,
)


def test_default_scheduler_plan_is_versioned_and_targets_explicit_actions() -> None:
    plan = default_scheduler_plan("personal")

    assert plan.configuration_version == 1
    assert plan.jobs[0].timezone == "Asia/Singapore"
    assert plan.jobs[0].actions == (
        ScheduleAction.REFRESH,
        ScheduleAction.RECONCILE,
        ScheduleAction.REPORT,
    )
    assert plan.jobs[1].timezone == "America/New_York"
    assert plan.jobs[1].pre_open_lead_minutes == 15
    assert plan.jobs[1].actions[-1] is ScheduleAction.ADVISORY
    assert all(job.catch_up_on_boot for job in plan.jobs)


def test_us_pre_open_schedule_follows_new_york_daylight_saving_time() -> None:
    job = ScheduledJob(
        "personal",
        "preopen",
        ScheduleJobKind.US_PRE_OPEN,
        (ScheduleAction.REFRESH, ScheduleAction.ADVISORY),
        pre_open_lead_minutes=15,
    )

    after_spring_change = job.next_run_at(datetime(2026, 3, 9, 12, tzinfo=UTC))
    after_autumn_change = job.next_run_at(datetime(2026, 11, 2, 12, tzinfo=UTC))

    assert after_spring_change == datetime(2026, 3, 9, 13, 15, tzinfo=UTC)
    assert after_autumn_change == datetime(2026, 11, 2, 14, 15, tzinfo=UTC)
    assert ScheduledJob(
        "personal",
        "weekly-report",
        ScheduleJobKind.SINGAPORE_REPORT,
        (ScheduleAction.REPORT,),
        cadence=ScheduleCadence.WEEKLY,
        weekday=0,
        singapore_hour=8,
        singapore_minute=30,
    ).next_run_at(datetime(2026, 1, 1, tzinfo=UTC)) == datetime(2026, 1, 5, 0, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="actions"):
        ScheduledJob("personal", "bad", ScheduleJobKind.US_PRE_OPEN, (), pre_open_lead_minutes=15)
    with pytest.raises(ValueError, match="catch up"):
        ScheduledJob(
            "personal",
            "non-persistent",
            ScheduleJobKind.SINGAPORE_REPORT,
            (ScheduleAction.REPORT,),
            singapore_hour=8,
            singapore_minute=30,
            catch_up_on_boot=False,
        )


def test_schedule_renderer_includes_profile_and_hour() -> None:
    output = render_schedule(ScheduleDefinition("personal", 8))
    assert "personal" in output
    assert "8" in output


def test_linux_schedule_uses_singapore_time_and_persistent_catchup() -> None:
    service, timer = render_systemd_units(ScheduleDefinition("personal", 18, 30))

    assert "TZ=Asia/Singapore" in service
    assert "18:30:00 Asia/Singapore" in timer
    assert "Persistent=true" in timer


def test_linux_schedule_status_reads_enabled_and_active_state(monkeypatch) -> None:
    monkeypatch.setattr(operator.platform, "system", lambda: "Linux")

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return Result(0 if command[2] == "is-enabled" else 3)

    monkeypatch.setattr(operator.subprocess, "run", run)

    status = linux_schedule_status(ScheduleDefinition("personal", 18))

    assert status.enabled is True
    assert status.active is False
    assert calls[0][3] == "com.stonks-cli.personal.timer"


def test_telegram_notification_posts_without_persisting_secret(monkeypatch) -> None:
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def open_request(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(operator, "urlopen", open_request)

    assert notify_telegram("token", "chat", "Title", "Message") is True
    assert requests[0][0].full_url == "https://api.telegram.org/bottoken/sendMessage"
    assert b"Title\\nMessage" in requests[0][0].data
