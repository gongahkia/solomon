from __future__ import annotations

from stonks_cli.polymarket.journal import append_journal, read_journal


def test_journal_append_and_read(monkeypatch, tmp_path):
    from stonks_cli.polymarket import journal

    monkeypatch.setattr(journal, "default_state_dir", lambda: tmp_path)

    append_journal("event_a", value=1)
    append_journal("event_b", value=2)

    entries = read_journal(limit=10)

    assert len(entries) == 2
    assert entries[0]["event"] == "event_a"
    assert entries[1]["event"] == "event_b"
