from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleDefinition:
    profile: str
    hour_utc: int

    def __post_init__(self) -> None:
        if not 0 <= self.hour_utc <= 23:
            raise ValueError("schedule hour must be between 0 and 23")


def render_schedule(definition: ScheduleDefinition, executable: str = "stonks-cli") -> str:
    command = f"{executable} portfolio {definition.profile} --json"
    if platform.system() == "Darwin":
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<plist version="1.0"><dict><key>Label</key><string>com.stonks-cli.'
            f"{definition.profile}</string><key>ProgramArguments</key><array><string>{executable}</string>"
            f"<string>portfolio</string><string>{definition.profile}</string><string>--json</string></array>"
            f"<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{definition.hour_utc}</integer></dict></dict></plist>\n"
        )
    return (
        "[Unit]\nDescription=stonks-cli portfolio report\n\n[Service]\nType=oneshot\n"
        f"ExecStart={command}\n\n[Timer]\nOnCalendar=*-*-* {definition.hour_utc:02d}:00:00 UTC\nPersistent=true\n"
    )


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
