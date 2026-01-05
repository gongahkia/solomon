import json
import time

from stonks_cli.data.cache import load_cached_text, save_cached_text


def test_cache_ttl_expiry(tmp_path):
    key = "example-key"
    payload = "hello"

    save_cached_text(tmp_path, key, payload)

    # Sanity: no TTL means cache is always valid.
    assert load_cached_text(tmp_path, key, ttl_seconds=0) == payload

    # Force the cache entry to be old enough to expire.
    cache_file = next(tmp_path.glob("*.json"))
    obj = json.loads(cache_file.read_text(encoding="utf-8"))
    obj["created_at"] = time.time() - 10_000
    cache_file.write_text(json.dumps(obj), encoding="utf-8")

    assert load_cached_text(tmp_path, key, ttl_seconds=60) is None
