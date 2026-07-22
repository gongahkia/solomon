from __future__ import annotations

from stonks_cli import operator
from stonks_cli.operator import (
    ScheduleDefinition,
    linux_schedule_status,
    notify_telegram,
    render_schedule,
    render_systemd_units,
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
