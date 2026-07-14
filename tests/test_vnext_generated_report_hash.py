from __future__ import annotations

import hashlib

import pytest

from stonks_cli.vnext.generated_report_hash import GeneratedReportHash, hash_generated_report


def test_generated_report_hash_is_deterministic_and_serializable(tmp_path):
    path = tmp_path / "daily-report.md"
    contents = b"# Daily Report\n\nall values verified\n"
    path.write_bytes(contents)

    result = hash_generated_report(path)

    assert result == GeneratedReportHash(path, hashlib.sha256(contents).hexdigest(), len(contents))
    assert result.to_data() == {"path": str(path), "sha256": hashlib.sha256(contents).hexdigest(), "byte_count": len(contents)}


@pytest.mark.parametrize("path", [None, "daily-report.md"])
def test_generated_report_hash_fails_closed_for_malformed_paths(path):
    with pytest.raises(ValueError, match="generated report"):
        hash_generated_report(path)  # type: ignore[arg-type]


def test_generated_report_hash_rejects_symlinked_external_data(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("content", encoding="utf-8")
    linked = tmp_path / "linked.md"
    linked.symlink_to(report)

    with pytest.raises(ValueError, match="regular file"):
        hash_generated_report(linked)


@pytest.mark.parametrize("sha256,byte_count", [("A" * 64, 1), ("a" * 63, 1), ("a" * 64, -1)])
def test_generated_report_hash_result_rejects_malformed_data(tmp_path, sha256, byte_count):
    with pytest.raises(ValueError, match="generated-report hash"):
        GeneratedReportHash(tmp_path / "report.md", sha256, byte_count)
