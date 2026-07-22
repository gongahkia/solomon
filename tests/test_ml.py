from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from conftest import encrypted_ledger

from stonks_cli.ml import latest_model, predict_trend, store_model, train_instrument_trend_model


def _points() -> tuple[tuple[date, Decimal], ...]:
    value = Decimal("100")
    result = []
    for index in range(100):
        value *= Decimal("1.01") if index % 3 else Decimal("0.995")
        result.append((date(2026, 1, 1) + timedelta(days=index), value))
    return tuple(result)


def test_trend_model_uses_chronological_validation_and_encrypted_storage(tmp_path, monkeypatch) -> None:
    model = train_instrument_trend_model("US:SPY", _points())
    prediction = predict_trend(model, _points())
    ledger = encrypted_ledger(tmp_path, monkeypatch)

    store_model(ledger, model)

    assert 0 <= model.validation_accuracy <= 1
    assert prediction.as_of == date(2026, 4, 10)
    assert 0 <= prediction.upward_probability <= 1
    assert latest_model(ledger, "US:SPY") == model
