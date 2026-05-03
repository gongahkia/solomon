from __future__ import annotations

import pandas as pd

from stonks_cli.portfolio.optimization import optimize_weights


def test_optimize_weights_risk_parity_sums_to_one() -> None:
    idx = pd.date_range("2025-01-01", periods=120, freq="D")
    prices = pd.DataFrame(
        {
            "AAPL.US": [100 + i for i in range(120)],
            "MSFT.US": [200 + i * 0.5 for i in range(120)],
            "SPY.US": [400 + i * 0.2 for i in range(120)],
        },
        index=idx,
    )

    weights = optimize_weights(prices, method="risk_parity", lookback=60)

    assert set(weights) == {"AAPL.US", "MSFT.US", "SPY.US"}
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert all(w >= 0 for w in weights.values())


def test_optimize_weights_equal_for_single_asset() -> None:
    prices = pd.DataFrame({"AAPL.US": [100.0, 101.0, 102.0]})

    assert optimize_weights(prices, method="mean_variance") == {"AAPL.US": 1.0}
