from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from stonks_cli.errors import ProviderError
from stonks_cli.storage import EncryptedLedger


@dataclass(frozen=True)
class TrendModel:
    model_id: str
    instrument_key: str
    trained_through: date
    feature_means: tuple[float, float, float, float]
    feature_scales: tuple[float, float, float, float]
    coefficients: tuple[float, float, float, float]
    intercept: float
    validation_accuracy: float
    validation_periods: int


@dataclass(frozen=True)
class TrendPrediction:
    model_id: str
    instrument_key: str
    as_of: date
    upward_probability: float
    validation_accuracy: float
    validation_periods: int


def train_trend_model(points: tuple[tuple[date, Decimal], ...]) -> TrendModel:
    if len(points) < 61:
        raise ProviderError("ML trend model requires at least 61 daily prices")
    if any(points[index][0] >= points[index + 1][0] for index in range(len(points) - 1)):
        raise ProviderError("ML prices must be strictly chronological")
    samples = [(_features(points, index), int(points[index + 1][1] > points[index][1])) for index in range(20, len(points) - 1)]
    split = int(len(samples) * 0.7)
    if split < 20 or len(samples) - split < 10:
        raise ProviderError("ML trend model requires sufficient train and validation periods")
    train, validation = samples[:split], samples[split:]
    means = _four(sum(row[0][index] for row in train) / len(train) for index in range(4))
    scales = _four(
        max(math.sqrt(sum((row[0][index] - means[index]) ** 2 for row in train) / len(train)), 1e-9)
        for index in range(4)
    )
    normalized_train = [(_normalize(features, means, scales), label) for features, label in train]
    coefficients = [0.0, 0.0, 0.0, 0.0]
    intercept = 0.0
    for _ in range(400):
        gradient = [0.0, 0.0, 0.0, 0.0]
        intercept_gradient = 0.0
        for features, label in normalized_train:
            error = _probability(intercept + sum(weight * value for weight, value in zip(coefficients, features, strict=True))) - label
            intercept_gradient += error
            for index, value in enumerate(features):
                gradient[index] += error * value
        rate = 0.08 / len(normalized_train)
        intercept -= rate * intercept_gradient
        coefficients = [weight - rate * gradient[index] for index, weight in enumerate(coefficients)]
    correct = sum(
        1
        if (
            _probability(
                intercept
                + sum(
                    weight * value
                    for weight, value in zip(
                        coefficients, _normalize(features, means, scales), strict=True
                    )
                )
            )
            >= 0.5
        )
        == label
        else 0
        for features, label in validation
    )
    payload = {
        "instrument_key": "",
        "trained_through": points[20 + split][0].isoformat(),
        "feature_means": means,
        "feature_scales": scales,
        "coefficients": coefficients,
        "intercept": intercept,
        "validation_accuracy": correct / len(validation),
        "validation_periods": len(validation),
    }
    model_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return TrendModel(
        model_id,
        "",
        points[20 + split][0],
        means,
        scales,
        _four(coefficients),
        intercept,
        correct / len(validation),
        len(validation),
    )


def train_instrument_trend_model(
    instrument_key: str, points: tuple[tuple[date, Decimal], ...]
) -> TrendModel:
    model = train_trend_model(points)
    payload = asdict(model) | {"instrument_key": instrument_key}
    model_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return TrendModel(
        model_id,
        instrument_key,
        model.trained_through,
        model.feature_means,
        model.feature_scales,
        model.coefficients,
        model.intercept,
        model.validation_accuracy,
        model.validation_periods,
    )


def predict_trend(model: TrendModel, points: tuple[tuple[date, Decimal], ...]) -> TrendPrediction:
    if len(points) < 21:
        raise ProviderError("ML prediction requires at least 21 daily prices")
    probability = _probability(
        model.intercept
        + sum(
            weight * value
            for weight, value in zip(
                model.coefficients,
                _normalize(_features(points, len(points) - 1), model.feature_means, model.feature_scales),
                strict=True,
            )
        )
    )
    return TrendPrediction(
        model.model_id,
        model.instrument_key,
        points[-1][0],
        probability,
        model.validation_accuracy,
        model.validation_periods,
    )


def store_model(ledger: EncryptedLedger, model: TrendModel) -> None:
    with ledger.connection() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS trend_models (model_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO trend_models VALUES (?, ?)",
            (model.model_id, json.dumps(asdict(model), sort_keys=True, default=str)),
        )


def latest_model(ledger: EncryptedLedger, instrument_key: str) -> TrendModel:
    with ledger.connection() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS trend_models (model_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        rows = connection.execute("SELECT payload FROM trend_models").fetchall()
    models = [_model_from_payload(row[0]) for row in rows]
    candidates = [model for model in models if model.instrument_key == instrument_key]
    if not candidates:
        raise ProviderError("ML model is unavailable for instrument")
    return max(candidates, key=lambda item: (item.trained_through, item.model_id))


def _features(points: tuple[tuple[date, Decimal], ...], index: int) -> tuple[float, float, float, float]:
    close = float(points[index][1])
    returns = [float(points[item][1] / points[item - 1][1] - Decimal("1")) for item in range(index - 4, index + 1)]
    mean = sum(returns) / len(returns)
    volatility = math.sqrt(sum((value - mean) ** 2 for value in returns) / len(returns))
    return (
        float(points[index][1] / points[index - 1][1] - Decimal("1")),
        float(points[index][1] / points[index - 5][1] - Decimal("1")),
        float(points[index][1] / points[index - 20][1] - Decimal("1")),
        volatility if close else 0.0,
    )


def _normalize(
    features: tuple[float, float, float, float],
    means: tuple[float, float, float, float],
    scales: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        (features[0] - means[0]) / scales[0],
        (features[1] - means[1]) / scales[1],
        (features[2] - means[2]) / scales[2],
        (features[3] - means[3]) / scales[3],
    )


def _probability(value: float) -> float:
    return 1 / (1 + math.exp(-max(min(value, 60), -60)))


def _four(values: Iterable[float]) -> tuple[float, float, float, float]:
    items = tuple(float(item) for item in values)
    if len(items) != 4:
        raise ValueError("ML feature vector must contain four values")
    return items[0], items[1], items[2], items[3]


def _model_from_payload(payload: str) -> TrendModel:
    data = json.loads(payload)
    return TrendModel(
        data["model_id"],
        data["instrument_key"],
        date.fromisoformat(data["trained_through"]),
        tuple(data["feature_means"]),
        tuple(data["feature_scales"]),
        tuple(data["coefficients"]),
        data["intercept"],
        data["validation_accuracy"],
        data["validation_periods"],
    )
