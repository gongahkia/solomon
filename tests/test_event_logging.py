from __future__ import annotations

import json

from stonks_cli.logging_utils import track_event
from stonks_cli.paths import default_state_dir


def test_track_event_persists_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    track_event("test.event", feature="snapshot", ok=True)

    path = default_state_dir() / "events.jsonl"
    assert path.exists()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["event"] == "test.event"
    assert payload["feature"] == "snapshot"
    assert payload["ok"] is True
