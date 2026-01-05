import json

from stonks_cli.analysis.backtest import BacktestMetrics
from stonks_cli.analysis.strategy import Recommendation
from stonks_cli.reporting.json_report import write_json_report
from stonks_cli.reporting.report import TickerResult


def test_json_report_includes_structured_sizing_fields(tmp_path) -> None:
    out = tmp_path / "report.json"
    results = [
        TickerResult(
            ticker="TEST.US",
            last_close=123.45,
            recommendation=Recommendation(action="BUY_DCA", confidence=0.7, rationale="ok"),
            backtest=BacktestMetrics(cagr=0.1, sharpe=1.2, max_drawdown=-0.2),
            suggested_position_fraction=0.15,
            vol_annualized=0.30,
            atr14=2.5,
            stop_loss=118.0,
            take_profit=130.0,
        )
    ]

    write_json_report(results, out_path=out, portfolio=None)
    payload = json.loads(out.read_text(encoding="utf-8"))

    r0 = payload["results"][0]
    assert r0["suggested_position_fraction"] == 0.15
    assert r0["vol_annualized"] == 0.30
    assert r0["atr14"] == 2.5
    assert r0["stop_loss"] == 118.0
    assert r0["take_profit"] == 130.0
