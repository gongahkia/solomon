import io

import pandas as pd
from rich.console import Console

from stonks_cli.config import AppConfig, DataConfig, RiskConfig
from stonks_cli.pipeline import compute_results


def test_compute_results_populates_data_sufficiency_fields(tmp_path) -> None:
    # Minimal close-only series; ensures missing_columns is populated.
    n = 80
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "ticker": ["TEST" for _ in range(n)],
            "close": [float(i + 1) for i in range(n)],
        }
    )
    csv_path = tmp_path / "prices.csv"
    df.to_csv(csv_path, index=False)

    cfg = AppConfig(
        tickers=["TEST.US"],
        data=DataConfig(provider="csv", csv_path=str(csv_path), cache_ttl_seconds=0, concurrency_limit=1),
        risk=RiskConfig(min_history_days=60),
        deterministic=True,
    )

    console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    results, _portfolio = compute_results(cfg, console)
    assert len(results) == 1

    r0 = results[0]
    assert r0.rows_used == n
    assert r0.last_date == "2020-03-20"
    assert "volume" in (r0.missing_columns or [])
    assert "high" in (r0.missing_columns or [])
    assert "low" in (r0.missing_columns or [])
    assert "open" in (r0.missing_columns or [])
