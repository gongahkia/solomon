from __future__ import annotations

import gzip
import hashlib

import pytest

from stonks_cli.vnext.historical_storage import compact_historical_storage


def test_historical_storage_compacts_repetitive_data_without_deleting_the_source(tmp_path):
    source = tmp_path / "history.jsonl"
    contents = (b'{"event":"portfolio.snapshot","value":1}\n' * 1000)
    source.write_bytes(contents)
    destination = tmp_path / "archives" / "history.jsonl.gz"

    compaction = compact_historical_storage(source, destination)

    assert compaction.destination == destination
    assert compaction.source_sha256 == hashlib.sha256(contents).hexdigest()
    assert compaction.source_bytes == len(contents)
    assert compaction.compressed_bytes < len(contents)
    assert gzip.decompress(destination.read_bytes()) == contents
    assert source.read_bytes() == contents
    assert destination.stat().st_mode & 0o777 == 0o600


def test_historical_storage_fails_closed_without_a_size_reduction_or_on_existing_destination(tmp_path):
    source = tmp_path / "history.jsonl"
    source.write_bytes(b"small")
    destination = tmp_path / "history.jsonl.gz"

    with pytest.raises(ValueError, match="did not reduce size"):
        compact_historical_storage(source, destination)
    assert destination.exists() is False
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        compact_historical_storage(source, destination)


@pytest.mark.parametrize("source", [None, "history.jsonl"])
def test_historical_storage_rejects_malformed_source_paths(source, tmp_path):
    with pytest.raises(ValueError, match="source must be"):
        compact_historical_storage(source, tmp_path / "history.jsonl.gz")  # type: ignore[arg-type]
