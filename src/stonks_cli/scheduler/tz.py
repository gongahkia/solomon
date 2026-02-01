from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger


def resolve_timezone(name: str | None):
    """Resolve a timezone name.

    Supports:
    - "local": the system local timezone
    - IANA timezone names (e.g., "America/New_York")
    - common aliases like "UTC"
    """

    tz_name = (name or "local").strip() or "local"
    if tz_name.lower() == "local":
        local_tz = datetime.now().astimezone().tzinfo
        return local_tz or UTC

    try:
        return ZoneInfo(tz_name)
    except Exception as e:
        raise ValueError(f"Invalid timezone: {tz_name}") from e


def cron_trigger_from_config(cron: str, timezone_name: str | None) -> CronTrigger:
    tz = resolve_timezone(timezone_name)
    return CronTrigger.from_crontab(cron, timezone=tz)
