import pytest

from stonks_cli.config import AppConfig
from stonks_cli.vnext.errors import VNextConfigurationError
from stonks_cli.vnext.weekly_operator_reports import (
    WEEKLY_OPERATOR_REPORT_JOB_ID,
    WeeklyOperatorReportSchedule,
    schedule_weekly_operator_reports,
)


class _Scheduler:
    def __init__(self) -> None:
        self.calls = []

    def add_job(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


def _config() -> AppConfig:
    return AppConfig.model_validate({"vnext": {"enabled": True, "features": {"operator_reports": True}}})


def test_weekly_operator_report_schedule_registers_one_inert_utc_cron_job():
    scheduler = _Scheduler()
    calls = []

    schedule_weekly_operator_reports(_config(), scheduler, lambda: calls.append("ran"), WeeklyOperatorReportSchedule(0, 17, 30))

    assert calls == []
    assert scheduler.calls[0][1] == {
        "trigger": "cron",
        "id": WEEKLY_OPERATOR_REPORT_JOB_ID,
        "replace_existing": True,
        "day_of_week": 0,
        "hour": 17,
        "minute": 30,
        "timezone": "UTC",
        "coalesce": True,
        "max_instances": 1,
    }


def test_weekly_operator_report_schedule_fails_closed_for_disabled_config_or_invalid_schedule():
    with pytest.raises(VNextConfigurationError, match="not enabled"):
        schedule_weekly_operator_reports(AppConfig(), _Scheduler(), lambda: None, WeeklyOperatorReportSchedule(0, 17, 30))
    with pytest.raises(ValueError, match="weekday"):
        WeeklyOperatorReportSchedule(7, 0, 0)
