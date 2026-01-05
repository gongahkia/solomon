from pathlib import Path

from stonks_cli.analysis.backtest import BacktestMetrics
from stonks_cli.analysis.strategy import Recommendation
from stonks_cli.reporting.report import TickerResult, write_text_report


def test_portfolio_backtest_summary_is_in_header(tmp_path: Path):
    out_dir = tmp_path / "out"

    r = TickerResult(
        ticker="AAPL.US",
        last_close=100.0,
        recommendation=Recommendation(action="BUY_DCA", confidence=0.5, rationale="r"),
    )
    portfolio = BacktestMetrics(cagr=0.10, sharpe=1.23, max_drawdown=-0.20)

    report_path = write_text_report([r], out_dir=out_dir, portfolio=portfolio, name="report_latest.txt")
    text = report_path.read_text(encoding="utf-8")

    # The portfolio summary should appear before the main per-ticker table.
    assert text.find("Portfolio Backtest") != -1
    assert text.find("Portfolio Backtest") < text.find("Ticker")
