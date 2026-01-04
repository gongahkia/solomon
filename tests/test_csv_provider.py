from __future__ import annotations

import pandas as pd

from stonks_cli.data.providers import CsvProvider


def test_csv_provider_filters_raw_or_suffixed_ticker(tmp_path):
    csv_path = tmp_path / "prices.csv"
    dates = pd.date_range("2024-01-01", periods=3, freq="D")

    df = pd.DataFrame(
        {
            "date": list(dates) + list(dates),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
            "ticker": ["AAPL", "AAPL", "AAPL", "MSFT.US", "MSFT.US", "MSFT.US"],
        }
    )
    df.to_csv(csv_path, index=False)

    provider = CsvProvider(str(csv_path))

    aapl = provider.fetch_daily("AAPL.US")
    assert aapl.ticker == "AAPL.US"
    assert not aapl.df.empty

    msft = provider.fetch_daily("MSFT")
    assert msft.ticker == "MSFT.US"
    assert not msft.df.empty
