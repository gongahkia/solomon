from __future__ import annotations

import hashlib

import pytest

from stonks_cli.vnext.report_output_hash import ReportOutputHash, hash_report_output_data


def test_report_output_hash_binds_exact_rendered_utf8_output():
    rendered = "DAILY REPORT\nstatus: verified ✓\n"

    result = hash_report_output_data("daily.report", rendered)

    assert result == ReportOutputHash("daily.report", hashlib.sha256(rendered.encode("utf-8")).hexdigest(), len(rendered), len(rendered.encode("utf-8")))
    assert result.to_data()["sha256"] == result.sha256


@pytest.mark.parametrize("report_id,rendered_output", [("Daily", "report"), ("daily.report", None), ("daily.report", b"report")])
def test_report_output_hash_fails_closed_for_malformed_external_data(report_id, rendered_output):
    with pytest.raises((TypeError, ValueError), match="report-output"):
        hash_report_output_data(report_id, rendered_output)  # type: ignore[arg-type]


@pytest.mark.parametrize("sha256,character_count,byte_count", [("A" * 64, 1, 1), ("a" * 63, 1, 1), ("a" * 64, -1, 1)])
def test_report_output_hash_result_rejects_malformed_data(sha256, character_count, byte_count):
    with pytest.raises(ValueError, match="report-output hash"):
        ReportOutputHash("daily.report", sha256, character_count, byte_count)
