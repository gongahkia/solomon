from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from conftest import encrypted_ledger

from stonks_cli.advisory import (
    list_research_artifacts,
    research_candidates,
    store_research_artifact,
)
from stonks_cli.market_data import DailyPrice, store_daily_prices
from stonks_cli.ml import store_model, train_instrument_trend_model
from stonks_cli.types import Currency, Instrument


def test_research_artifact_is_local_experimental_and_non_executing(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    instrument = Instrument("SPY", "US", Currency.USD)
    prices = []
    value = Decimal("100")
    for index in range(100):
        value *= Decimal("1.01") if index % 3 else Decimal("0.995")
        prices.append(DailyPrice(instrument, date(2026, 1, 1) + timedelta(days=index), value, "a" * 64))
    store_daily_prices(ledger, prices)
    store_model(
        ledger,
        train_instrument_trend_model(
            instrument.key, tuple((item.session_date, item.close) for item in prices)
        ),
    )

    candidates = research_candidates(ledger, (instrument.key,), minimum_validation_accuracy=0)
    artifact = store_research_artifact(ledger, candidates)

    assert candidates[0].disposition == "research_candidate"
    assert "no_execution" in candidates[0].risk_flags
    assert list_research_artifacts(ledger)[0].artifact_id == artifact.artifact_id
