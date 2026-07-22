from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


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
