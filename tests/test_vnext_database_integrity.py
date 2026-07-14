from __future__ import annotations

import sqlite3

from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.database_integrity import check_database_integrity


def test_database_integrity_check_reports_healthy_database(tmp_path):
    factory = SQLiteConnectionFactory(tmp_path / "vnext.sqlite3")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))")
        connection.execute("INSERT INTO parents(id) VALUES (1)")
        connection.execute("INSERT INTO children(parent_id) VALUES (1)")

    report = check_database_integrity(factory)

    assert report.healthy is True
    assert report.integrity_messages == ("ok",)
    assert report.foreign_key_violations == ()


def test_database_integrity_check_fails_closed_for_foreign_key_violations(tmp_path):
    path = tmp_path / "vnext.sqlite3"
    factory = SQLiteConnectionFactory(path)
    with factory.connect() as connection:
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("INSERT INTO children(parent_id) VALUES (99)")

    report = check_database_integrity(factory)

    assert report.healthy is False
    assert report.integrity_messages == ("ok",)
    assert report.foreign_key_violations[0].table == "children"
    assert report.foreign_key_violations[0].parent_table == "parents"


def test_database_integrity_check_reports_healthy_after_foreign_key_recovery(tmp_path):
    path = tmp_path / "vnext.sqlite3"
    factory = SQLiteConnectionFactory(path)
    with factory.connect() as connection:
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("INSERT INTO children(parent_id) VALUES (99)")

    assert check_database_integrity(factory).healthy is False
    with factory.connect() as connection:
        connection.execute("DELETE FROM children WHERE parent_id = 99")

    report = check_database_integrity(factory)

    assert report.healthy is True
    assert report.foreign_key_violations == ()
