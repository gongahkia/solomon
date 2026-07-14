from __future__ import annotations

import sqlite3

import pytest

from stonks_cli.vnext.database import SQLiteConnectionFactory


def test_sqlite_connection_factory_creates_safe_wal_connection(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "nested" / "vnext.sqlite3")

    with factory.connect() as connection:
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO children(parent_id) VALUES (1)")
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_sqlite_connection_factory_read_only_connection_cannot_write(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "vnext.sqlite3")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")

    with factory.connect(read_only=True) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO events(id) VALUES (1)")


def test_sqlite_connection_factory_read_only_missing_database_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        SQLiteConnectionFactory(tmp_path / "missing.sqlite3").connect(read_only=True)


@pytest.mark.parametrize("path,timeout", [("relative.sqlite3", 5.0), (None, 5.0), ("/tmp/test.sqlite3", 0), ("/tmp/test.sqlite3", float("inf"))])
def test_sqlite_connection_factory_rejects_malformed_configuration(path, timeout):
    with pytest.raises((TypeError, ValueError)):
        SQLiteConnectionFactory(path, timeout)
