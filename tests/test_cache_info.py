from __future__ import annotations

from stonks_cli.commands import do_data_cache_info
from stonks_cli.data.cache import save_cached_text
from stonks_cli.paths import default_cache_dir


def test_data_cache_info_counts_entries(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    cache_dir = default_cache_dir()
    # Create a couple of cache entries.
    save_cached_text(cache_dir, "k1", "payload1")
    save_cached_text(cache_dir, "k2", "payload2")

    info = do_data_cache_info()
    assert info["cache_dir"] == str(cache_dir)
    assert int(info["entries"]) >= 2
    assert int(info["size_bytes"]) > 0
    assert isinstance(info["examples"], list)
