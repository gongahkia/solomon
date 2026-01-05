from pathlib import Path

from stonks_cli.analysis.strategy import Recommendation
from stonks_cli.reporting.report import TickerResult, write_text_report


def test_text_report_is_sorted_by_action_and_confidence(tmp_path: Path):
    out_dir = tmp_path / "out"
    r1 = TickerResult(
        ticker="ZZZ.US",
        last_close=100.0,
        recommendation=Recommendation(action="AVOID_OR_HEDGE", confidence=0.99, rationale="r1"),
    )
    r2 = TickerResult(
        ticker="AAA.US",
        last_close=100.0,
        recommendation=Recommendation(action="BUY_DCA", confidence=0.10, rationale="r2"),
    )
    report_path = write_text_report([r1, r2], out_dir=out_dir, name="report_latest.txt")
    text = report_path.read_text(encoding="utf-8")

    # BUY actions should come before AVOID actions, regardless of confidence.
    assert text.find("AAA.US") < text.find("ZZZ.US")
