from __future__ import annotations

from stonks_cli.operator import ScheduleDefinition, render_schedule


def test_schedule_renderer_includes_profile_and_hour() -> None:
    output = render_schedule(ScheduleDefinition("personal", 8))
    assert "personal" in output
    assert "8" in output
