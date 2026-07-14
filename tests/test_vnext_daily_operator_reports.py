import pytest

from stonks_cli.config import AppConfig
from stonks_cli.vnext.daily_operator_reports import (
    DAILY_OPERATOR_REPORT_JOB_ID,
    DailyOperatorReportSchedule,
    schedule_daily_operator_reports,
)
from stonks_cli.vnext.errors import VNextConfigurationError


class _Scheduler:
    def __init__(self) -> None:
        self.calls = []

    def add_job(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


def _config() -> AppConfig:
    return AppConfig.model_validate({"vnext": {"enabled": True, "features": {"operator_reports": True}}})


def test_daily_operator_report_schedule_registers_one_inert_utc_cron_job():
    scheduler = _Scheduler()
    calls = []

    schedule_daily_operator_reports(_config(), scheduler, lambda: calls.append("ran"), DailyOperatorReportSchedule(17, 30))

    assert calls == []
    assert scheduler.calls[0][1] == {
        "trigger": "cron",
        "id": DAILY_OPERATOR_REPORT_JOB_ID,
        "replace_existing": True,
        "hour": 17,
        "minute": 30,
        "timezone": "UTC",
        "coalesce": True,
        "max_instances": 1,
    }


def test_daily_operator_report_schedule_fails_closed_for_disabled_config_or_invalid_schedule():
    with pytest.raises(VNextConfigurationError, match="not enabled"):
        schedule_daily_operator_reports(AppConfig(), _Scheduler(), lambda: None, DailyOperatorReportSchedule(17, 30))
    with pytest.raises(ValueError, match="hour"):
        DailyOperatorReportSchedule(24, 0)
