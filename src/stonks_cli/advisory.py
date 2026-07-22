from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from stonks_cli.errors import ProviderError
from stonks_cli.market_data import historical_prices
from stonks_cli.ml import latest_model, predict_trend
from stonks_cli.storage import EncryptedLedger


@dataclass(frozen=True)
class ResearchCandidate:
    instrument_key: str
    model_id: str
    as_of: str
    upward_probability: float
    validation_accuracy: float
    validation_periods: int
    disposition: str = "research_candidate"
    risk_flags: tuple[str, ...] = ("experimental_price_only_model", "no_execution")


@dataclass(frozen=True)
class ResearchArtifact:
    artifact_id: str
    created_at: datetime
    candidates: tuple[ResearchCandidate, ...]

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("research artifact time must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


def research_candidates(
    ledger: EncryptedLedger,
    instrument_keys: tuple[str, ...],
    *,
    minimum_validation_accuracy: float,
) -> tuple[ResearchCandidate, ...]:
    if not 0 <= minimum_validation_accuracy <= 1:
        raise ValueError("minimum validation accuracy must be between zero and one")
    candidates: list[ResearchCandidate] = []
    for instrument_key in sorted(set(instrument_keys)):
        try:
            prediction = predict_trend(
                latest_model(ledger, instrument_key), historical_prices(ledger, instrument_key)
            )
        except ProviderError:
            continue
        if prediction.validation_accuracy < minimum_validation_accuracy:
            continue
        candidates.append(
            ResearchCandidate(
                instrument_key,
                prediction.model_id,
                prediction.as_of.isoformat(),
                prediction.upward_probability,
                prediction.validation_accuracy,
                prediction.validation_periods,
            )
        )
    return tuple(
        sorted(candidates, key=lambda item: (-item.upward_probability, item.instrument_key))
    )


def store_research_artifact(
    ledger: EncryptedLedger, candidates: tuple[ResearchCandidate, ...]
) -> ResearchArtifact:
    created_at = datetime.now(UTC)
    payload = {
        "candidates": [asdict(candidate) for candidate in candidates],
        "created_at": created_at.isoformat(),
    }
    artifact = ResearchArtifact(
        hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        created_at,
        candidates,
    )
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT OR IGNORE INTO research_artifacts VALUES (?, ?, ?)",
            (
                artifact.artifact_id,
                artifact.created_at.isoformat(),
                json.dumps([asdict(candidate) for candidate in candidates], sort_keys=True),
            ),
        )
    return artifact


def list_research_artifacts(ledger: EncryptedLedger) -> tuple[ResearchArtifact, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM research_artifacts ORDER BY created_at, artifact_id").fetchall()
    return tuple(
        ResearchArtifact(
            row["artifact_id"],
            datetime.fromisoformat(row["created_at"]),
            tuple(_candidate_from_data(candidate) for candidate in json.loads(row["candidates"])),
        )
        for row in rows
    )


def _candidate_from_data(value: object) -> ResearchCandidate:
    if not isinstance(value, dict):
        raise ProviderError("stored research artifact is invalid")
    try:
        flags = value["risk_flags"]
        if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
            raise ValueError
        return ResearchCandidate(
            str(value["instrument_key"]),
            str(value["model_id"]),
            str(value["as_of"]),
            float(value["upward_probability"]),
            float(value["validation_accuracy"]),
            int(value["validation_periods"]),
            str(value["disposition"]),
            tuple(flags),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ProviderError("stored research artifact is invalid") from error


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_artifacts (
            artifact_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            candidates TEXT NOT NULL
        )
        """
    )
