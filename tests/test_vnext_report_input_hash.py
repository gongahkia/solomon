from __future__ import annotations

import hashlib

import pytest

from stonks_cli.vnext.report_input_hash import ReportInputHash, hash_report_input_data


def test_report_input_hash_is_deterministic_across_equivalent_mapping_orders():
    first = hash_report_input_data("portfolio.snapshot", {"assets": ["BTC", "ETH"], "as_of": "2026-07-14", "count": 2})
    second = hash_report_input_data("portfolio.snapshot", {"count": 2, "as_of": "2026-07-14", "assets": ["BTC", "ETH"]})

    assert first == second
    assert first == ReportInputHash("portfolio.snapshot", hashlib.sha256(b'{"as_of":"2026-07-14","assets":["BTC","ETH"],"count":2}').hexdigest(), 55)


@pytest.mark.parametrize(
    "source_id,data",
    [
        ("Portfolio", {}),
        ("portfolio.snapshot", None),
        ("portfolio.snapshot", {"score": float("nan")}),
        ("portfolio.snapshot", {"assets": {"BTC", "ETH"}}),
    ],
)
def test_report_input_hash_fails_closed_for_malformed_external_data(source_id, data):
    with pytest.raises((TypeError, ValueError), match="report-input"):
        hash_report_input_data(source_id, data)  # type: ignore[arg-type]


@pytest.mark.parametrize("sha256,byte_count", [("A" * 64, 2), ("a" * 64, 1), ("a" * 63, 2)])
def test_report_input_hash_result_rejects_malformed_data(sha256, byte_count):
    with pytest.raises(ValueError, match="report-input hash"):
        ReportInputHash("portfolio.snapshot", sha256, byte_count)
