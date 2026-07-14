from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from stonks_cli.vnext.foundation import (
    RUN_IDENTITY_VERSION,
    FrozenUTCClock,
    SecretReference,
    SystemUTCClock,
    as_utc,
    create_run_identity,
    load_run_identity,
    resolve_environment_secret,
    save_run_identity,
)


def test_system_utc_clock_returns_aware_utc_time():
    timestamp = SystemUTCClock().now()

    assert timestamp.tzinfo is UTC
    assert timestamp.utcoffset() == timedelta(0)


def test_secret_reference_holds_only_valid_environment_variable_name():
    reference = SecretReference.parse("env:STONKS_CLI_MOOMOO_TOKEN")

    assert reference.environment_variable == "STONKS_CLI_MOOMOO_TOKEN"
    assert str(reference) == "env:STONKS_CLI_MOOMOO_TOKEN"
    assert "token-value" not in repr(reference)


@pytest.mark.parametrize("value", [None, "STONKS_CLI_TOKEN", "env:", "env:token", "env:INVALID-NAME"])
def test_secret_reference_rejects_malformed_values(value):
    with pytest.raises((TypeError, ValueError)):
        SecretReference.parse(value)


def test_environment_secret_resolver_returns_present_value_without_logging_it():
    reference = SecretReference.parse("env:STONKS_CLI_MOOMOO_TOKEN")

    assert resolve_environment_secret(reference, {"STONKS_CLI_MOOMOO_TOKEN": "token-value"}) == "token-value"


@pytest.mark.parametrize("environment", [{}, {"STONKS_CLI_MOOMOO_TOKEN": ""}, {"STONKS_CLI_MOOMOO_TOKEN": 1}])
def test_environment_secret_resolver_fails_closed_without_secret_value(environment):
    reference = SecretReference.parse("env:STONKS_CLI_MOOMOO_TOKEN")

    with pytest.raises(ValueError, match="secret unavailable:STONKS_CLI_MOOMOO_TOKEN") as error:
        resolve_environment_secret(reference, environment)

    assert "token-value" not in str(error.value)


def test_environment_secret_resolver_rejects_non_reference_input():
    with pytest.raises(TypeError, match="secret reference is required"):
        resolve_environment_secret("env:STONKS_CLI_MOOMOO_TOKEN", {})


def test_frozen_utc_clock_normalizes_time_and_is_deterministic():
    clock = FrozenUTCClock(datetime(2026, 7, 14, 10, 0, tzinfo=timezone(timedelta(hours=8))))

    assert clock.now() == datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
    assert clock.now() == clock.now()


@pytest.mark.parametrize("value", [datetime(2026, 7, 14, 2, 0), "2026-07-14T02:00:00Z", None])
def test_utc_conversion_rejects_naive_and_malformed_values(value):
    with pytest.raises((TypeError, ValueError)):
        as_utc(value)


def test_run_identity_persists_once_and_round_trips(tmp_path):
    path = tmp_path / "runs" / "run.json"
    identity = create_run_identity(
        FrozenUTCClock(datetime(2026, 7, 14, 2, 0, tzinfo=UTC)),
        run_id=UUID("12345678-1234-5678-1234-567812345678"),
    )

    save_run_identity(path, identity)

    assert load_run_identity(path) == identity
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        save_run_identity(path, identity)


@pytest.mark.parametrize(
    "contents",
    [
        "not-json",
        '{"version": 2, "run_id": "12345678-1234-5678-1234-567812345678", "started_at": "2026-07-14T02:00:00Z"}',
        '{"version": true, "run_id": "12345678-1234-5678-1234-567812345678", "started_at": "2026-07-14T02:00:00Z"}',
        f'{{"version": {RUN_IDENTITY_VERSION}, "run_id": "not-a-uuid", "started_at": "2026-07-14T02:00:00Z"}}',
        f'{{"version": {RUN_IDENTITY_VERSION}, "run_id": "12345678-1234-5678-1234-567812345678"}}',
    ],
)
def test_malformed_persisted_run_identity_fails_closed(tmp_path, contents):
    path = tmp_path / "run.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError):
        load_run_identity(path)
