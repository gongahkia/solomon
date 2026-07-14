from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import VNextInvariantError
from stonks_cli.vnext.foundation import FrozenUTCClock
from stonks_cli.vnext.migrations import Migration, MigrationRegistry, MigrationRunner


def _create_events_table(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")


def _create_reports_table(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY)")


def test_migration_registry_returns_deterministic_pending_plan():
    registry = MigrationRegistry(
        (
            Migration(1, "create_events", _create_events_table),
            Migration(2, "create_reports", _create_reports_table),
        )
    )

    assert registry.latest_version == 2
    assert tuple(migration.name for migration in registry.pending_after(0)) == ("create_events", "create_reports")
    assert tuple(migration.name for migration in registry.pending_after(1)) == ("create_reports",)
    assert registry.pending_after(2) == ()


@pytest.mark.parametrize(
    "migrations",
    [
        (),
        (Migration(2, "create_events", _create_events_table),),
        (Migration(1, "create_events", _create_events_table), Migration(3, "create_reports", _create_reports_table)),
        (Migration(1, "duplicate", _create_events_table), Migration(2, "duplicate", _create_reports_table)),
    ],
)
def test_migration_registry_rejects_malformed_registration(migrations):
    with pytest.raises(ValueError):
        MigrationRegistry(migrations)


@pytest.mark.parametrize("version", [-1, 3, True, "1"])
def test_migration_registry_rejects_invalid_applied_version(version):
    registry = MigrationRegistry((Migration(1, "create_events", _create_events_table),))

    with pytest.raises(ValueError):
        registry.pending_after(version)


def test_migration_runner_applies_each_migration_once_and_persists_history(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "vnext.sqlite3")
    registry = MigrationRegistry(
        (
            Migration(1, "create_events", _create_events_table),
            Migration(2, "create_reports", _create_reports_table),
        )
    )
    runner = MigrationRunner(factory, registry, FrozenUTCClock(datetime(2026, 7, 14, 2, tzinfo=UTC)))

    assert tuple(migration.version for migration in runner.run()) == (1, 2)
    assert runner.run() == ()
    with factory.connect(read_only=True) as connection:
        rows = connection.execute("SELECT version, name, applied_at FROM vnext_schema_migrations ORDER BY version").fetchall()

    assert [(row["version"], row["name"], row["applied_at"]) for row in rows] == [
        (1, "create_events", "2026-07-14T02:00:00Z"),
        (2, "create_reports", "2026-07-14T02:00:00Z"),
    ]


def test_migration_runner_rolls_back_failed_migration_batch(tmp_path):
    def fail_after_create(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE broken (id INTEGER PRIMARY KEY)")
        raise RuntimeError("broken migration")

    factory = SQLiteConnectionFactory(tmp_path / "vnext.sqlite3")
    registry = MigrationRegistry((Migration(1, "create_events", _create_events_table), Migration(2, "fail_after_create", fail_after_create)))
    runner = MigrationRunner(factory, registry, FrozenUTCClock(datetime(2026, 7, 14, 2, tzinfo=UTC)))

    with pytest.raises(RuntimeError, match="broken migration"):
        runner.run()
    with factory.connect(read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM vnext_schema_migrations").fetchone()[0] == 0


def test_migration_runner_rejects_drifted_persisted_history(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "vnext.sqlite3")
    registry = MigrationRegistry((Migration(1, "create_events", _create_events_table),))
    runner = MigrationRunner(factory, registry, FrozenUTCClock(datetime(2026, 7, 14, 2, tzinfo=UTC)))

    runner.run()
    with factory.connect() as connection:
        connection.execute("UPDATE vnext_schema_migrations SET name = 'wrong_name' WHERE version = 1")
    with pytest.raises(VNextInvariantError, match="migration history does not match registry"):
        runner.run()
