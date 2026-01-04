from __future__ import annotations

import json
import time

from stonks_cli.commands import do_data_purge
from stonks_cli.data.cache import save_cached_text
from stonks_cli.paths import default_cache_dir


def test_data_purge_deletes_older_than_days(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    cache_dir = default_cache_dir()
    save_cached_text(cache_dir, "k_old", "old")
    save_cached_text(cache_dir, "k_new", "new")

    files = sorted([p for p in cache_dir.glob("*.json") if p.is_file()])
    assert len(files) >= 2

    # Mark the first file as very old by editing created_at.
    old_path = files[0]
    payload = json.loads(old_path.read_text(encoding="utf-8"))
    payload["created_at"] = time.time() - (10 * 86400)
    old_path.write_text(json.dumps(payload), encoding="utf-8")

    out = do_data_purge(older_than_days=1)
    assert out["cache_dir"] == str(cache_dir)
    assert int(out["deleted"]) >= 1

    remaining = [p for p in cache_dir.glob("*.json") if p.is_file()]
    assert len(remaining) >= 1


def test_data_purge_without_threshold_deletes_all(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    cache_dir = default_cache_dir()
    save_cached_text(cache_dir, "k1", "p1")
    save_cached_text(cache_dir, "k2", "p2")

    out = do_data_purge()
    assert int(out["deleted"]) >= 2
    assert not any(p.is_file() for p in cache_dir.glob("*.json"))
