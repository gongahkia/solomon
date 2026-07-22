from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

_JOB_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SINGAPORE = ZoneInfo("Asia/Singapore")
_NEW_YORK = ZoneInfo("America/New_York")


class ScheduleCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class ScheduleJobKind(StrEnum):
    SINGAPORE_REPORT = "singapore_report"
    US_PRE_OPEN = "us_pre_open"


class ScheduleAction(StrEnum):
    REFRESH = "refresh"
    RECONCILE = "reconcile"
    REPORT = "report"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class ScheduledJob:
    profile: str
    identifier: str
    kind: ScheduleJobKind
    actions: tuple[ScheduleAction, ...]
    cadence: ScheduleCadence = ScheduleCadence.DAILY
    singapore_hour: int | None = None
    singapore_minute: int | None = None
    weekday: int | None = None
    pre_open_lead_minutes: int | None = None
    enabled: bool = True
    version: int = 1
    catch_up_on_boot: bool = True

    def __post_init__(self) -> None:
        profile = self.profile.strip()
        identifier = self.identifier.strip().lower()
        if not profile or not _JOB_IDENTIFIER.fullmatch(identifier):
            raise ValueError("scheduler job profile and identifier are required")
        if not isinstance(self.kind, ScheduleJobKind):
            raise ValueError("scheduler job kind is invalid")
        if not isinstance(self.cadence, ScheduleCadence):
            raise ValueError("scheduler job cadence is invalid")
        if not self.actions or any(not isinstance(action, ScheduleAction) for action in self.actions):
            raise ValueError("scheduler job actions are required")
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("scheduler job actions must be unique")
        if not isinstance(self.enabled, bool) or not isinstance(self.catch_up_on_boot, bool):
            raise ValueError("scheduler job flags must be boolean")
        if not self.catch_up_on_boot:
            raise ValueError("scheduler jobs must catch up after host boot")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("scheduler job version must be a positive integer")
        if self.cadence is ScheduleCadence.WEEKLY:
            if not isinstance(self.weekday, int) or isinstance(self.weekday, bool) or not 0 <= self.weekday <= 6:
                raise ValueError("weekly scheduler jobs require a weekday")
        elif self.weekday is not None:
            raise ValueError("daily scheduler jobs must not specify a weekday")
        if self.kind is ScheduleJobKind.SINGAPORE_REPORT:
            if (
                not isinstance(self.singapore_hour, int)
                or isinstance(self.singapore_hour, bool)
                or not 0 <= self.singapore_hour <= 23
                or not isinstance(self.singapore_minute, int)
                or isinstance(self.singapore_minute, bool)
                or not 0 <= self.singapore_minute <= 59
                or self.pre_open_lead_minutes is not None
            ):
                raise ValueError("Singapore scheduler jobs require a valid local time")
        elif (
            self.singapore_hour is not None
            or self.singapore_minute is not None
            or not isinstance(self.pre_open_lead_minutes, int)
            or isinstance(self.pre_open_lead_minutes, bool)
            or self.pre_open_lead_minutes < 1
        ):
            raise ValueError("US pre-open scheduler jobs require a valid lead time")
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "identifier", identifier)

    @property
    def label(self) -> str:
        return f"com.stonks-cli.{self.profile}.{self.identifier}"

    @property
    def timezone(self) -> str:
        return "Asia/Singapore" if self.kind is ScheduleJobKind.SINGAPORE_REPORT else "America/New_York"

    def next_run_at(self, now: datetime) -> datetime | None:
        if now.tzinfo is None:
            raise ValueError("scheduler current time must be timezone-aware")
        if not self.enabled:
            return None
        zone = _SINGAPORE if self.kind is ScheduleJobKind.SINGAPORE_REPORT else _NEW_YORK
        current = now.astimezone(zone)
        days = 8 + (self.pre_open_lead_minutes or 0) // (24 * 60)
        for offset in range(days):
            candidate_day = current.date() + timedelta(days=offset)
            if self.cadence is ScheduleCadence.WEEKLY and candidate_day.weekday() != self.weekday:
                continue
            if self.kind is ScheduleJobKind.SINGAPORE_REPORT:
                assert self.singapore_hour is not None
                assert self.singapore_minute is not None
                candidate = datetime.combine(
                    candidate_day, time(self.singapore_hour, self.singapore_minute), tzinfo=zone
                )
            else:
                assert self.pre_open_lead_minutes is not None
                candidate = datetime.combine(candidate_day, time(9, 30), tzinfo=zone) - timedelta(
                    minutes=self.pre_open_lead_minutes
                )
            if candidate > current:
                return candidate.astimezone(UTC)
        raise ValueError("scheduler job has no next run")


@dataclass(frozen=True)
class SchedulerPlan:
    profile: str
    jobs: tuple[ScheduledJob, ...]
    configuration_version: int = 1

    def __post_init__(self) -> None:
        profile = self.profile.strip()
        if not profile or not self.jobs or any(job.profile != profile for job in self.jobs):
            raise ValueError("scheduler plan must contain jobs for one profile")
        if len({job.identifier for job in self.jobs}) != len(self.jobs):
            raise ValueError("scheduler plan job identifiers must be unique")
        if (
            not isinstance(self.configuration_version, int)
            or isinstance(self.configuration_version, bool)
            or self.configuration_version < 1
        ):
            raise ValueError("scheduler plan version must be a positive integer")
        object.__setattr__(self, "profile", profile)


def default_scheduler_plan(profile: str) -> SchedulerPlan:
    return SchedulerPlan(
        profile,
        (
            ScheduledJob(
                profile,
                "daily-report",
                ScheduleJobKind.SINGAPORE_REPORT,
                (ScheduleAction.REFRESH, ScheduleAction.RECONCILE, ScheduleAction.REPORT),
                singapore_hour=8,
                singapore_minute=30,
            ),
            ScheduledJob(
                profile,
                "us-pre-open-advisory",
                ScheduleJobKind.US_PRE_OPEN,
                (ScheduleAction.REFRESH, ScheduleAction.RECONCILE, ScheduleAction.ADVISORY),
                pre_open_lead_minutes=15,
            ),
        ),
    )


@dataclass(frozen=True)
class ScheduleDefinition:
    profile: str
    hour_singapore: int
    minute_singapore: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.hour_singapore <= 23:
            raise ValueError("schedule hour must be between 0 and 23")
        if not 0 <= self.minute_singapore <= 59:
            raise ValueError("schedule minute must be between 0 and 59")

    @property
    def label(self) -> str:
        return f"com.stonks-cli.{self.profile}"


@dataclass(frozen=True)
class ScheduleStatus:
    label: str
    enabled: bool
    active: bool


def render_schedule(definition: ScheduleDefinition, executable: str = "stonks-cli") -> str:
    command = f"{executable} monitor {definition.profile}"
    if platform.system() == "Darwin":
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<plist version="1.0"><dict><key>Label</key><string>com.stonks-cli.'
            f"{definition.profile}</string><key>ProgramArguments</key><array><string>{executable}</string>"
            f"<string>monitor</string><string>{definition.profile}</string></array>"
            f"<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{definition.hour_singapore}</integer>"
            f"<key>Minute</key><integer>{definition.minute_singapore}</integer></dict></dict></plist>\n"
        )
    return (
        "[Unit]\nDescription=stonks-cli portfolio report\n\n[Service]\nType=oneshot\n"
        f"Environment=TZ=Asia/Singapore\nExecStart={command}\n\n[Timer]\n"
        f"OnCalendar=*-*-* {definition.hour_singapore:02d}:{definition.minute_singapore:02d}:00 Asia/Singapore\n"
        "Persistent=true\n"
    )


def render_systemd_units(
    definition: ScheduleDefinition, executable: str = "stonks-cli"
) -> tuple[str, str]:
    command = f"{executable} monitor {definition.profile}"
    service = (
        "[Unit]\nDescription=stonks-cli portfolio report\n\n[Service]\nType=oneshot\n"
        f"Environment=TZ=Asia/Singapore\nExecStart={command}\n"
    )
    timer = (
        "[Unit]\nDescription=stonks-cli portfolio schedule\n\n[Timer]\n"
        f"OnCalendar=*-*-* {definition.hour_singapore:02d}:{definition.minute_singapore:02d}:00 Asia/Singapore\n"
        "Persistent=true\nUnit="
        f"{definition.label}.service\n\n[Install]\nWantedBy=timers.target\n"
    )
    return service, timer


def install_linux_schedule(
    definition: ScheduleDefinition, unit_directory: Path, executable: str = "stonks-cli"
) -> tuple[Path, Path]:
    if platform.system() != "Linux":
        raise ValueError("Linux systemd scheduling is unavailable on this host")
    service, timer = render_systemd_units(definition, executable)
    unit_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    service_path = unit_directory / f"{definition.label}.service"
    timer_path = unit_directory / f"{definition.label}.timer"
    for path, content in ((service_path, service), (timer_path, timer)):
        path.write_text(content)
        path.chmod(0o600)
    for command in (
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", timer_path.name),
    ):
        result = subprocess.run(command, check=False, capture_output=True)
        if result.returncode != 0:
            raise ValueError("systemd schedule installation failed")
    return service_path, timer_path


def install_macos_schedule(
    definition: ScheduleDefinition, agent_directory: Path, executable: str = "stonks-cli"
) -> Path:
    if platform.system() != "Darwin":
        raise ValueError("macOS launchd scheduling is unavailable on this host")
    agent_directory = agent_directory.expanduser().resolve()
    agent_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    agent_directory.chmod(0o700)
    path = agent_directory / f"{definition.label}.plist"
    if path.exists():
        raise ValueError("macOS schedule already exists")
    path.write_text(render_schedule(definition, executable))
    path.chmod(0o600)
    result = subprocess.run(
        ("launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        path.unlink(missing_ok=True)
        raise ValueError("macOS schedule installation failed")
    return path


def linux_schedule_status(definition: ScheduleDefinition) -> ScheduleStatus:
    if platform.system() != "Linux":
        raise ValueError("Linux systemd scheduling is unavailable on this host")

    def is_state(command: str) -> bool:
        return (
            subprocess.run(
                ("systemctl", "--user", command, f"{definition.label}.timer"),
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )

    return ScheduleStatus(definition.label, is_state("is-enabled"), is_state("is-active"))


def macos_schedule_status(definition: ScheduleDefinition) -> ScheduleStatus:
    if platform.system() != "Darwin":
        raise ValueError("macOS launchd scheduling is unavailable on this host")
    result = subprocess.run(
        ("launchctl", "print", f"gui/{os.getuid()}/{definition.label}"),
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout if isinstance(result.stdout, str) else ""
    return ScheduleStatus(definition.label, result.returncode == 0, "state = running" in output)


def notify_local(title: str, message: str) -> bool:
    system = platform.system()
    if system == "Darwin":
        escaped_title = title.replace('"', '\\"')
        escaped_message = message.replace('"', '\\"')
        return (
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{escaped_message}" with title "{escaped_title}"',
                ],
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )
    if system == "Linux":
        return (
            subprocess.run(
                ["notify-send", title, message], check=False, capture_output=True
            ).returncode
            == 0
        )
    return False


def notify_telegram(token: str, chat_id: str, title: str, message: str) -> bool:
    if not token.strip() or not chat_id.strip():
        raise ValueError("Telegram token and chat ID are required")
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": f"{title}\n{message}"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            return isinstance(status, int) and status == 200
    except (OSError, URLError):
        return False
