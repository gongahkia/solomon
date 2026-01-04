from __future__ import annotations

import pytest

from stonks_cli.scheduler.tz import cron_trigger_from_config, resolve_timezone


def test_resolve_timezone_local_returns_tzinfo():
    tz = resolve_timezone("local")
    assert tz is not None


def test_resolve_timezone_utc_works():
    tz = resolve_timezone("UTC")
    # ZoneInfo('UTC') stringifies as 'UTC'
    assert str(tz) == "UTC"


def test_resolve_timezone_invalid_raises():
    with pytest.raises(ValueError):
        resolve_timezone("Not/A_Timezone")


def test_cron_trigger_uses_configured_timezone():
    trigger = cron_trigger_from_config("0 17 * * 1-5", "UTC")
    assert str(trigger.timezone) == "UTC"
