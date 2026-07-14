from __future__ import annotations

import sqlite3

import pytest

from stonks_cli.vnext.migrations import Migration, MigrationRegistry


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
