from datetime import UTC, datetime

import pytest

from stonks_cli.config import AppConfig
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, FXReferenceRateBatch
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.rebalance_drift import RebalanceTarget, calculate_rebalance_drift
from stonks_cli.vnext.weekly_operator_reports import WeeklyOperatorReportSchedule, schedule_weekly_operator_reports


def test_weekly_workflow_schedules_then_runs_one_read_only_rebalance_review():
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = PortfolioSnapshot(
        "moomoo",
        "100",
        captured_at,
        (
            PortfolioHolding("100", "sg", "SG.D05", PortfolioAssetClass.EQUITY, 1.0, "SGD", 100.0),
            PortfolioHolding("100", "us", "US.AAPL", PortfolioAssetClass.EQUITY, 1.0, "USD", 300.0),
        ),
    )
    rates = FXReferenceRateBatch("fixture", "USD", (FXReferenceRate("SGD", "USD", 0.75, captured_at),))
    reports = []

    class Scheduler:
        def add_job(self, job, **kwargs):
            self.job = job
            self.kwargs = kwargs

    scheduler = Scheduler()
    schedule_weekly_operator_reports(
        AppConfig.model_validate({"vnext": {"enabled": True, "features": {"operator_reports": True}}}),
        scheduler,
        lambda: reports.append(calculate_rebalance_drift(snapshot, rates, (RebalanceTarget("US.AAPL", 0.75), RebalanceTarget("SG.D05", 0.25)))),
        WeeklyOperatorReportSchedule(0, 17, 30),
    )

    assert reports == []
    scheduler.job()

    assert scheduler.kwargs["timezone"] == "UTC"
    assert [(item.symbol, item.drift_fraction) for item in reports[0]] == [
        ("SG.D05", pytest.approx(-0.05)),
        ("US.AAPL", pytest.approx(0.05)),
    ]
