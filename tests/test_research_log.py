from __future__ import annotations

from stonks_cli import research


def test_research_log_list_and_search(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(research, "default_state_dir", lambda: tmp_path)

    entry = research.add_research_entry("BTC basis", "Funding is elevated", tags=["crypto"])
    rows = research.list_research_entries()
    matches = research.search_research_entries("funding")

    assert rows[0].entry_id == entry.entry_id
    assert matches[0].title == "BTC basis"
    assert matches[0].tags == ["crypto"]
