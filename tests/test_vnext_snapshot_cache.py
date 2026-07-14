import pytest

from stonks_cli.vnext.snapshot_cache import IdempotentSnapshotCache


def test_idempotent_snapshot_cache_caches_only_successful_values_until_ttl():
    now = [0.0]
    calls = [0]
    cache = IdempotentSnapshotCache[str, str](30, clock=lambda: now[0])

    def load() -> str:
        calls[0] += 1
        return f"snapshot-{calls[0]}"

    assert cache.get_or_load("100", load) == "snapshot-1"
    assert cache.get_or_load("100", load) == "snapshot-1"
    now[0] = 30
    assert cache.get_or_load("100", load) == "snapshot-2"


def test_idempotent_snapshot_cache_does_not_cache_load_failures():
    cache = IdempotentSnapshotCache[str, str](30, clock=lambda: 0.0)
    with pytest.raises(RuntimeError):
        cache.get_or_load("100", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
    assert cache.get_or_load("100", lambda: "recovered") == "recovered"
