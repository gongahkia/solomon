from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from stonks_cli.config import BenchmarkComponent, BenchmarkSettings, canonical_benchmark_identifier
from stonks_cli.errors import ProfileError, ProviderError
from stonks_cli.market_data import FxRate, FxRateResolution, resolve_fx_rate
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import Currency

_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SOURCE_HASH = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BenchmarkTotalReturnPoint:
    identifier: str
    currency: Currency
    session_date: date
    index_level: Decimal
    source_hash: str
    as_of_at: datetime | None = None
    provider_id: str = "csv"

    def __post_init__(self) -> None:
        try:
            identifier = canonical_benchmark_identifier(self.identifier)
        except ProfileError as error:
            raise ValueError(str(error)) from error
        if not isinstance(self.currency, Currency):
            raise ValueError("benchmark currency is invalid")
        if not isinstance(self.session_date, date):
            raise ValueError("benchmark session date is required")
        try:
            index_level = Decimal(self.index_level)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("benchmark total-return index level must be decimal") from error
        if not index_level.is_finite() or index_level <= 0:
            raise ValueError("benchmark total-return index level must be positive")
        source_hash = self.source_hash.lower()
        if not _SOURCE_HASH.fullmatch(source_hash):
            raise ValueError("benchmark source hash must be a SHA-256 digest")
        as_of_at = self.as_of_at or datetime(
            self.session_date.year, self.session_date.month, self.session_date.day, tzinfo=UTC
        )
        if as_of_at.tzinfo is None:
            raise ValueError("benchmark as-of time must be timezone-aware")
        as_of_at = as_of_at.astimezone(UTC)
        if as_of_at.date() != self.session_date:
            raise ValueError("benchmark as-of time must match its session date")
        provider_id = self.provider_id.strip().lower()
        if not _PROVIDER.fullmatch(provider_id):
            raise ValueError("benchmark provider identifier is invalid")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "index_level", index_level)
        object.__setattr__(self, "source_hash", source_hash)
        object.__setattr__(self, "as_of_at", as_of_at)
        object.__setattr__(self, "provider_id", provider_id)


@dataclass(frozen=True)
class BenchmarkComponentPeriod:
    component: BenchmarkComponent
    status: str
    reason: str | None
    start: BenchmarkTotalReturnPoint | None
    end: BenchmarkTotalReturnPoint | None
    native_return: Decimal | None
    reporting_return: Decimal | None
    start_fx: FxRateResolution | None
    end_fx: FxRateResolution | None


@dataclass(frozen=True)
class BenchmarkPeriodReport:
    start_date: date
    end_date: date
    reporting_currency: Currency
    configuration_version: int
    components: tuple[BenchmarkComponentPeriod, ...]
    aggregate_return: Decimal | None
    status: str


@dataclass(frozen=True)
class BenchmarkBlendAudit:
    configuration_version: int
    origin: str
    source_retrieved_at: datetime
    source_provenance: tuple[str, ...]
    data_status: str
    components: tuple[BenchmarkComponent, ...]


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_total_return_points (
            identifier TEXT NOT NULL,
            currency TEXT NOT NULL,
            session_date TEXT NOT NULL,
            index_level TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            as_of_at TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            UNIQUE(identifier, session_date, source_hash)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_blend_audits (
            configuration_version INTEGER NOT NULL,
            origin TEXT NOT NULL,
            source_retrieved_at TEXT NOT NULL,
            source_provenance_json TEXT NOT NULL,
            data_status TEXT NOT NULL,
            components_json TEXT NOT NULL,
            UNIQUE(configuration_version, origin, source_retrieved_at)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS benchmark_total_return_points_lookup
        ON benchmark_total_return_points(identifier, session_date, as_of_at)
        """
    )


def store_total_return_points(ledger: EncryptedLedger, points: tuple[BenchmarkTotalReturnPoint, ...]) -> int:
    inserted = 0
    with ledger.connection() as connection:
        _initialize(connection)
        for point in points:
            as_of_at = point.as_of_at
            if as_of_at is None:
                raise ValueError("benchmark as-of time is required")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO benchmark_total_return_points (
                    identifier, currency, session_date, index_level, source_hash, as_of_at, provider_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.identifier,
                    point.currency.value,
                    point.session_date.isoformat(),
                    str(point.index_level),
                    point.source_hash,
                    as_of_at.isoformat(),
                    point.provider_id,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def import_total_return_csv(ledger: EncryptedLedger, path: Path) -> int:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise ProviderError("benchmark CSV must be UTF-8") from error
    required = {"date", "identifier", "currency", "total_return_index"}
    if rows.fieldnames is None or not required <= set(rows.fieldnames):
        raise ProviderError("benchmark CSV requires date,identifier,currency,total_return_index")
    points: list[BenchmarkTotalReturnPoint] = []
    for row in rows:
        try:
            points.append(
                BenchmarkTotalReturnPoint(
                    row["identifier"] or "",
                    Currency((row["currency"] or "").upper()),
                    date.fromisoformat(row["date"] or ""),
                    Decimal(row["total_return_index"] or ""),
                    source_hash,
                    datetime.fromisoformat(row["as_of_at"])
                    if row.get("as_of_at")
                    else None,
                    row.get("provider_id") or "csv",
                )
            )
        except (KeyError, ValueError, InvalidOperation) as error:
            raise ProviderError("benchmark CSV contains invalid data") from error
    return store_total_return_points(ledger, tuple(points))


def latest_total_return_points(
    ledger: EncryptedLedger,
) -> dict[tuple[str, date], BenchmarkTotalReturnPoint]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT identifier, currency, session_date, index_level, source_hash, as_of_at, provider_id
            FROM benchmark_total_return_points
            ORDER BY identifier, session_date, as_of_at DESC, source_hash ASC
            """
        ).fetchall()
    points: dict[tuple[str, date], BenchmarkTotalReturnPoint] = {}
    for row in rows:
        key = (row["identifier"], date.fromisoformat(row["session_date"]))
        if key not in points:
            points[key] = BenchmarkTotalReturnPoint(
                row["identifier"],
                Currency(row["currency"]),
                key[1],
                Decimal(row["index_level"]),
                row["source_hash"],
                datetime.fromisoformat(row["as_of_at"]),
                row["provider_id"],
            )
    return points


def component_data_availability(
    settings: BenchmarkSettings, points: dict[tuple[str, date], BenchmarkTotalReturnPoint]
) -> tuple[str, ...]:
    component_currencies = {
        component.identifier: component.currency for component in settings.components
    }
    available = {
        identifier
        for (identifier, _), point in points.items()
        if component_currencies.get(identifier) is point.currency
    }
    return tuple(
        component.identifier for component in settings.components if component.identifier not in available
    )


def record_blend_audit(
    ledger: EncryptedLedger,
    settings: BenchmarkSettings,
    *,
    origin: str,
    source_retrieved_at: datetime,
    source_provenance: tuple[str, ...],
    data_status: str,
) -> BenchmarkBlendAudit:
    if source_retrieved_at.tzinfo is None:
        raise ValueError("benchmark source retrieval time must be timezone-aware")
    origin = origin.strip().lower()
    if not _PROVIDER.fullmatch(origin.replace("-", "_")):
        raise ValueError("benchmark audit origin is invalid")
    if not source_provenance or not all(isinstance(item, str) and item.strip() for item in source_provenance):
        raise ValueError("benchmark source provenance is required")
    if data_status not in {"available", "unavailable"}:
        raise ValueError("benchmark data status is invalid")
    retrieved_at = source_retrieved_at.astimezone(UTC)
    audit = BenchmarkBlendAudit(
        settings.version,
        origin,
        retrieved_at,
        tuple(item.strip() for item in source_provenance),
        data_status,
        settings.components,
    )
    components_json = json.dumps(
        [
            {
                "identifier": component.identifier,
                "name": component.name,
                "currency": component.currency.value,
                "weight": component.weight,
                "source_url": component.source_url,
                "return_basis": component.return_basis,
            }
            for component in settings.components
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO benchmark_blend_audits (
                configuration_version, origin, source_retrieved_at, source_provenance_json, data_status,
                components_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                audit.configuration_version,
                audit.origin,
                audit.source_retrieved_at.isoformat(),
                json.dumps(audit.source_provenance, separators=(",", ":")),
                audit.data_status,
                components_json,
            ),
        )
    return audit


def blend_audits(ledger: EncryptedLedger) -> tuple[BenchmarkBlendAudit, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT configuration_version, origin, source_retrieved_at, source_provenance_json, data_status,
                   components_json
            FROM benchmark_blend_audits
            ORDER BY configuration_version, source_retrieved_at
            """
        ).fetchall()
    return tuple(
        BenchmarkBlendAudit(
            int(row["configuration_version"]),
            row["origin"],
            datetime.fromisoformat(row["source_retrieved_at"]),
            tuple(json.loads(row["source_provenance_json"])),
            row["data_status"],
            tuple(
                BenchmarkComponent(
                    item["identifier"],
                    item["name"],
                    Currency(item["currency"]),
                    item["weight"],
                    item["source_url"],
                    item["return_basis"],
                )
                for item in json.loads(row["components_json"])
            ),
        )
        for row in rows
    )


def calculate_period_report(
    settings: BenchmarkSettings,
    points: dict[tuple[str, date], BenchmarkTotalReturnPoint],
    *,
    start_date: date,
    end_date: date,
    reporting_currency: Currency,
    start_fx_rates: dict[tuple[Currency, Currency], FxRate],
    end_fx_rates: dict[tuple[Currency, Currency], FxRate],
) -> BenchmarkPeriodReport:
    if not isinstance(start_date, date) or not isinstance(end_date, date) or start_date >= end_date:
        raise ValueError("benchmark period dates must be ordered")
    if not isinstance(reporting_currency, Currency):
        raise ValueError("benchmark reporting currency is invalid")
    components = tuple(
        _component_period(
            component,
            points,
            start_date,
            end_date,
            reporting_currency,
            start_fx_rates,
            end_fx_rates,
        )
        for component in settings.components
    )
    available = all(item.status == "available" for item in components)
    unavailable = any(item.status == "unavailable" for item in components)
    aggregate_return: Decimal | None
    if available:
        aggregate_return = sum(
            (
                item.component.decimal_weight * item.reporting_return
                for item in components
                if item.reporting_return is not None
            ),
            Decimal("0"),
        )
    else:
        aggregate_return = None
    return BenchmarkPeriodReport(
        start_date,
        end_date,
        reporting_currency,
        settings.version,
        components,
        aggregate_return,
        "available" if available else "unavailable" if unavailable else "stale",
    )


def _component_period(
    component: BenchmarkComponent,
    points: dict[tuple[str, date], BenchmarkTotalReturnPoint],
    start_date: date,
    end_date: date,
    reporting_currency: Currency,
    start_fx_rates: dict[tuple[Currency, Currency], FxRate],
    end_fx_rates: dict[tuple[Currency, Currency], FxRate],
) -> BenchmarkComponentPeriod:
    if component.return_basis != "total_return":
        return BenchmarkComponentPeriod(
            component,
            "unavailable",
            "component is not configured for a total-return series",
            None,
            None,
            None,
            None,
            None,
            None,
        )
    start = points.get((component.identifier, start_date))
    end = points.get((component.identifier, end_date))
    if start is None:
        return BenchmarkComponentPeriod(
            component,
            "unavailable",
            "missing start total-return index level",
            start,
            end,
            None,
            None,
            None,
            None,
        )
    if end is None:
        latest = max(
            (
                point
                for (identifier, session_date), point in points.items()
                if identifier == component.identifier and session_date < end_date
            ),
            key=lambda point: point.session_date,
            default=None,
        )
        if latest is not None:
            return BenchmarkComponentPeriod(
                component,
                "stale",
                "end total-return index level is stale",
                start,
                latest,
                None,
                None,
                None,
                None,
            )
        return BenchmarkComponentPeriod(
            component,
            "unavailable",
            "missing end total-return index level",
            start,
            None,
            None,
            None,
            None,
            None,
        )
    if start.currency is not component.currency or end.currency is not component.currency:
        return BenchmarkComponentPeriod(
            component,
            "unavailable",
            "total-return series currency does not match component configuration",
            start,
            end,
            None,
            None,
            None,
            None,
        )
    try:
        start_fx = resolve_fx_rate(component.currency, reporting_currency, start_fx_rates)
        end_fx = resolve_fx_rate(component.currency, reporting_currency, end_fx_rates)
    except ProviderError as error:
        return BenchmarkComponentPeriod(
            component,
            "unavailable",
            str(error),
            start,
            end,
            None,
            None,
            None,
            None,
        )
    native_return = end.index_level / start.index_level - Decimal("1")
    reporting_return = (
        end.index_level * end_fx.conversion_rate
        / (start.index_level * start_fx.conversion_rate)
        - Decimal("1")
    )
    return BenchmarkComponentPeriod(
        component,
        "available",
        None,
        start,
        end,
        native_return,
        reporting_return,
        start_fx,
        end_fx,
    )
