from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from stonks_cli.paths import default_state_dir
from stonks_cli.whalemirror.models import (
    BasisSnapshot,
    CarryDecision,
    CarryPosition,
    CarryQuote,
    FundingSnapshot,
    Venue,
    coerce_venue,
)

DEFAULT_RAW_RETENTION_DAYS = 7
DEFAULT_AGGREGATE_RETENTION_DAYS = 180


@dataclass(frozen=True)
class CarryStorageRetentionPolicy:
    raw_retention_days: int = DEFAULT_RAW_RETENTION_DAYS
    aggregate_retention_days: int = DEFAULT_AGGREGATE_RETENTION_DAYS

    def __post_init__(self) -> None:
        if self.raw_retention_days < 1:
            raise ValueError("raw_retention_days must be >= 1")
        if self.aggregate_retention_days < self.raw_retention_days:
            raise ValueError("aggregate_retention_days must be >= raw_retention_days")


@dataclass(frozen=True)
class CarryRetentionResult:
    compacted_raw_rows: int
    aggregate_rows: int
    deleted_raw_rows: int
    deleted_aggregate_rows: int


class CarryStorage:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_carry_storage_path()

    def initialize(self) -> None:
        with self._connect() as conn:
            _initialize_schema(conn)

    def write_quote(self, quote: CarryQuote) -> None:
        payload = quote.to_dict()
        with self._connect() as conn:
            _initialize_schema(conn)
            conn.execute(
                """
                INSERT INTO carry_quotes
                    (venue, asset, spot_mid, perp_mid, oracle_mid, mark_mid, timestamp, source_health, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["venue"],
                    payload["asset"],
                    payload["spot_mid"],
                    payload["perp_mid"],
                    payload["oracle_mid"],
                    payload["mark_mid"],
                    payload["timestamp"],
                    payload["source_health"],
                    _json_dump(payload),
                ),
            )

    def write_funding(self, snapshot: FundingSnapshot) -> None:
        payload = snapshot.to_dict()
        with self._connect() as conn:
            _initialize_schema(conn)
            conn.execute(
                """
                INSERT INTO carry_funding_snapshots
                    (venue, asset, hourly_rate, annualized_rate, next_funding_time, premium_index, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["venue"],
                    payload["asset"],
                    payload["hourly_rate"],
                    payload["annualized_rate"],
                    payload["next_funding_time"],
                    payload["premium_index"],
                    payload["timestamp"],
                    _json_dump(payload),
                ),
            )

    def write_basis(self, snapshot: BasisSnapshot, *, venue: Venue | str = Venue.HYPERLIQUID) -> None:
        payload = snapshot.to_dict()
        resolved_venue = coerce_venue(venue)
        with self._connect() as conn:
            _initialize_schema(conn)
            conn.execute(
                """
                INSERT INTO carry_basis_snapshots
                    (venue, asset, spot_mid, perp_mid, basis_abs, basis_pct, annualized_basis, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(resolved_venue),
                    payload["asset"],
                    payload["spot_mid"],
                    payload["perp_mid"],
                    payload["basis_abs"],
                    payload["basis_pct"],
                    payload["annualized_basis"],
                    payload["timestamp"],
                    _json_dump({"venue": str(resolved_venue), **payload}),
                ),
            )

    def write_decision(self, decision: CarryDecision) -> None:
        payload = decision.to_dict()
        with self._connect() as conn:
            _initialize_schema(conn)
            conn.execute(
                """
                INSERT INTO carry_decisions
                    (decision_id, mode, action, reason, inputs_json, risk_checks_json, expected_net_apr, exit_rule, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    mode=excluded.mode,
                    action=excluded.action,
                    reason=excluded.reason,
                    inputs_json=excluded.inputs_json,
                    risk_checks_json=excluded.risk_checks_json,
                    expected_net_apr=excluded.expected_net_apr,
                    exit_rule=excluded.exit_rule,
                    timestamp=excluded.timestamp,
                    payload_json=excluded.payload_json
                """,
                (
                    payload["decision_id"],
                    payload["mode"],
                    payload["action"],
                    payload["reason"],
                    _json_dump(payload["inputs"]),
                    _json_dump(payload["risk_checks"]),
                    payload["expected_net_apr"],
                    payload["exit_rule"],
                    payload["timestamp"],
                    _json_dump(payload),
                ),
            )

    def write_position(
        self,
        position: CarryPosition,
        *,
        timestamp: str,
        venue: Venue | str = Venue.HYPERLIQUID,
        decision_id: str | None = None,
    ) -> None:
        payload = position.to_dict()
        resolved_venue = coerce_venue(venue)
        with self._connect() as conn:
            _initialize_schema(conn)
            conn.execute(
                """
                INSERT INTO carry_positions
                    (decision_id, venue, asset, spot_qty, perp_qty, net_delta, entry_basis, accrued_funding, fees, margin_buffer, liquidation_distance, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    str(resolved_venue),
                    payload["asset"],
                    payload["spot_qty"],
                    payload["perp_qty"],
                    payload["net_delta"],
                    payload["entry_basis"],
                    payload["accrued_funding"],
                    payload["fees"],
                    payload["margin_buffer"],
                    payload["liquidation_distance"],
                    timestamp,
                    _json_dump({"decision_id": decision_id, "timestamp": timestamp, "venue": str(resolved_venue), **payload}),
                ),
            )

    def write_venue_health(
        self,
        *,
        venue: Venue | str,
        status: str,
        timestamp: str,
        latency_ms: float | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        resolved_venue = coerce_venue(venue)
        payload = {
            "latency_ms": latency_ms,
            "message": message,
            "metadata": metadata or {},
            "status": status,
            "timestamp": timestamp,
            "venue": str(resolved_venue),
        }
        with self._connect() as conn:
            _initialize_schema(conn)
            conn.execute(
                """
                INSERT INTO carry_venue_health
                    (venue, status, latency_ms, message, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(resolved_venue), status, latency_ms, message, timestamp, _json_dump(payload)),
            )

    def run_retention(
        self,
        policy: CarryStorageRetentionPolicy | None = None,
        *,
        now: datetime | None = None,
    ) -> CarryRetentionResult:
        policy = policy or CarryStorageRetentionPolicy()
        now = now or datetime.now(UTC)
        cutoff = _iso(now - timedelta(days=policy.raw_retention_days))
        aggregate_cutoff = (now - timedelta(days=policy.aggregate_retention_days)).date().isoformat()
        with self._connect() as conn:
            _initialize_schema(conn)
            compacted_raw_rows = 0
            aggregate_rows = 0
            deleted_raw_rows = 0
            for table, spec in _COMPACTED_TABLES.items():
                compacted, aggregates = _compact_table(conn, table=table, cutoff=cutoff, spec=spec)
                compacted_raw_rows += compacted
                aggregate_rows += aggregates
                cursor = conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
                deleted_raw_rows += cursor.rowcount
            cursor = conn.execute("DELETE FROM carry_daily_aggregates WHERE bucket_date < ?", (aggregate_cutoff,))
            deleted_aggregate_rows = cursor.rowcount
        return CarryRetentionResult(
            compacted_raw_rows=compacted_raw_rows,
            aggregate_rows=aggregate_rows,
            deleted_raw_rows=deleted_raw_rows,
            deleted_aggregate_rows=deleted_aggregate_rows,
        )

    def count_rows(self, table: str) -> int:
        if table not in _KNOWN_TABLES:
            raise ValueError(f"unknown carry storage table: {table}")
        with self._connect() as conn:
            _initialize_schema(conn)
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def default_carry_storage_path() -> Path:
    return default_state_dir() / "carrymirror.sqlite3"


def _initialize_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)


def _compact_table(conn: sqlite3.Connection, *, table: str, cutoff: str, spec: dict[str, Any]) -> tuple[int, int]:
    rows = conn.execute(f"SELECT * FROM {table} WHERE timestamp < ? ORDER BY timestamp", (cutoff,)).fetchall()
    buckets: dict[tuple[str, str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (
            spec["kind"],
            _bucket_date(str(row["timestamp"])),
            str(row["venue"]),
            str(row["asset"]) if "asset" in row.keys() else "",
        )
        buckets.setdefault(key, []).append(row)
    for (kind, bucket_date, venue, asset), bucket_rows in buckets.items():
        metrics = _aggregate_metrics(bucket_rows, spec["metrics"])
        first_timestamp = str(bucket_rows[0]["timestamp"])
        last_timestamp = str(bucket_rows[-1]["timestamp"])
        conn.execute(
            """
            INSERT INTO carry_daily_aggregates
                (kind, bucket_date, venue, asset, sample_count, first_timestamp, last_timestamp, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kind, bucket_date, venue, asset) DO UPDATE SET
                sample_count=excluded.sample_count,
                first_timestamp=excluded.first_timestamp,
                last_timestamp=excluded.last_timestamp,
                metrics_json=excluded.metrics_json
            """,
            (
                kind,
                bucket_date,
                venue,
                asset,
                len(bucket_rows),
                first_timestamp,
                last_timestamp,
                _json_dump(metrics),
            ),
        )
    return len(rows), len(buckets)


def _aggregate_metrics(rows: list[sqlite3.Row], metric_names: tuple[str, ...]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for name in metric_names:
        values = [float(row[name]) for row in rows if row[name] is not None]
        if values:
            metrics[name] = {
                "avg": sum(values) / len(values),
                "max": max(values),
                "min": min(values),
            }
    if "status" in rows[0].keys():
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row["status"])
            counts[status] = counts.get(status, 0) + 1
        metrics["status_counts"] = counts
    return metrics


def _bucket_date(timestamp: str) -> str:
    return _parse_timestamp(timestamp).date().isoformat()


def _parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


_COMPACTED_TABLES: dict[str, dict[str, Any]] = {
    "carry_quotes": {
        "kind": "quote",
        "metrics": ("spot_mid", "perp_mid", "oracle_mid", "mark_mid"),
    },
    "carry_funding_snapshots": {
        "kind": "funding",
        "metrics": ("hourly_rate", "annualized_rate", "premium_index"),
    },
    "carry_basis_snapshots": {
        "kind": "basis",
        "metrics": ("spot_mid", "perp_mid", "basis_abs", "basis_pct", "annualized_basis"),
    },
    "carry_positions": {
        "kind": "position",
        "metrics": ("spot_qty", "perp_qty", "net_delta", "entry_basis", "accrued_funding", "fees", "margin_buffer", "liquidation_distance"),
    },
    "carry_venue_health": {
        "kind": "venue_health",
        "metrics": ("latency_ms",),
    },
}

_KNOWN_TABLES = frozenset(
    {
        "carry_quotes",
        "carry_funding_snapshots",
        "carry_basis_snapshots",
        "carry_decisions",
        "carry_positions",
        "carry_venue_health",
        "carry_daily_aggregates",
    }
)

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS carry_quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venue TEXT NOT NULL,
        asset TEXT NOT NULL,
        spot_mid REAL,
        perp_mid REAL,
        oracle_mid REAL,
        mark_mid REAL,
        timestamp TEXT NOT NULL,
        source_health TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carry_quotes_lookup ON carry_quotes (venue, asset, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS carry_funding_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venue TEXT NOT NULL,
        asset TEXT NOT NULL,
        hourly_rate REAL NOT NULL,
        annualized_rate REAL NOT NULL,
        next_funding_time TEXT,
        premium_index REAL,
        timestamp TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carry_funding_lookup ON carry_funding_snapshots (venue, asset, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS carry_basis_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venue TEXT NOT NULL,
        asset TEXT NOT NULL,
        spot_mid REAL NOT NULL,
        perp_mid REAL NOT NULL,
        basis_abs REAL NOT NULL,
        basis_pct REAL NOT NULL,
        annualized_basis REAL NOT NULL,
        timestamp TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carry_basis_lookup ON carry_basis_snapshots (venue, asset, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS carry_decisions (
        decision_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        risk_checks_json TEXT NOT NULL,
        expected_net_apr REAL NOT NULL,
        exit_rule TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carry_decisions_time ON carry_decisions (timestamp)",
    """
    CREATE TABLE IF NOT EXISTS carry_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id TEXT,
        venue TEXT NOT NULL,
        asset TEXT NOT NULL,
        spot_qty REAL NOT NULL,
        perp_qty REAL NOT NULL,
        net_delta REAL NOT NULL,
        entry_basis REAL NOT NULL,
        accrued_funding REAL NOT NULL,
        fees REAL NOT NULL,
        margin_buffer REAL NOT NULL,
        liquidation_distance REAL NOT NULL,
        timestamp TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(decision_id) REFERENCES carry_decisions(decision_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carry_positions_lookup ON carry_positions (venue, asset, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS carry_venue_health (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venue TEXT NOT NULL,
        status TEXT NOT NULL,
        latency_ms REAL,
        message TEXT,
        timestamp TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_carry_venue_health_lookup ON carry_venue_health (venue, timestamp)",
    """
    CREATE TABLE IF NOT EXISTS carry_daily_aggregates (
        kind TEXT NOT NULL,
        bucket_date TEXT NOT NULL,
        venue TEXT NOT NULL,
        asset TEXT NOT NULL,
        sample_count INTEGER NOT NULL,
        first_timestamp TEXT NOT NULL,
        last_timestamp TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(kind, bucket_date, venue, asset)
    )
    """,
)
