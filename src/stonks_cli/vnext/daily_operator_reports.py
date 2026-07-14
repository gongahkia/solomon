from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stonks_cli.config import AppConfig
from stonks_cli.vnext.errors import VNextConfigurationError

DAILY_OPERATOR_REPORT_JOB_ID = "vnext.daily_operator_report"


@dataclass(frozen=True)
class DailyOperatorReportSchedule:
    hour_utc: int
    minute_utc: int

    def __post_init__(self) -> None:
        if not isinstance(self.hour_utc, int) or isinstance(self.hour_utc, bool) or not 0 <= self.hour_utc <= 23:
            raise ValueError("daily operator-report hour is invalid")
        if not isinstance(self.minute_utc, int) or isinstance(self.minute_utc, bool) or not 0 <= self.minute_utc <= 59:
            raise ValueError("daily operator-report minute is invalid")


def schedule_daily_operator_reports(
    config: AppConfig, scheduler: object, report_job: Callable[[], None], schedule: DailyOperatorReportSchedule
) -> None:
    if not isinstance(config, AppConfig):
        raise TypeError("daily operator reports require app configuration")
    if not config.vnext.enabled or not config.vnext.features.operator_reports:
        raise VNextConfigurationError("vNext operator reports are not enabled")
    if not isinstance(schedule, DailyOperatorReportSchedule):
        raise TypeError("daily operator-report schedule is invalid")
    if not callable(report_job):
        raise TypeError("daily operator-report job is invalid")
    add_job = getattr(scheduler, "add_job", None)
    if not callable(add_job):
        raise TypeError("daily operator-report scheduler is invalid")
    add_job(
        report_job,
        trigger="cron",
        id=DAILY_OPERATOR_REPORT_JOB_ID,
        replace_existing=True,
        hour=schedule.hour_utc,
        minute=schedule.minute_utc,
        timezone="UTC",
        coalesce=True,
        max_instances=1,
    )
