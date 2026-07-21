from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stonks_cli.ledger import cash_balances, positions
from stonks_cli.types import BrokerPositionSnapshot, Currency, LedgerEvent


@dataclass(frozen=True)
class ReconciliationDifference:
    subject: str
    expected: Decimal
    observed: Decimal

    @property
    def delta(self) -> Decimal:
        return self.observed - self.expected


def reconcile(
    expected_cash: dict[tuple[str, Currency], Decimal],
    observed_cash: dict[tuple[str, Currency], Decimal],
    expected_positions: dict[tuple[str, str], Decimal],
    observed_positions: dict[tuple[str, str], Decimal],
) -> tuple[ReconciliationDifference, ...]:
    differences: list[ReconciliationDifference] = []
    for key in sorted(
        set(expected_cash) | set(observed_cash), key=lambda item: (item[0], item[1].value)
    ):
        expected, observed = (
            expected_cash.get(key, Decimal("0")),
            observed_cash.get(key, Decimal("0")),
        )
        if expected != observed:
            differences.append(
                ReconciliationDifference(f"cash:{key[0]}:{key[1].value}", expected, observed)
            )
    for position_key in sorted(set(expected_positions) | set(observed_positions)):
        expected, observed = (
            expected_positions.get(position_key, Decimal("0")),
            observed_positions.get(position_key, Decimal("0")),
        )
        if expected != observed:
            differences.append(
                ReconciliationDifference(
                    f"position:{position_key[0]}:{position_key[1]}", expected, observed
                )
            )
    return tuple(differences)


def broker_positions(
    snapshots: list[BrokerPositionSnapshot],
) -> dict[tuple[str, str], Decimal]:
    latest: dict[tuple[str, str], BrokerPositionSnapshot] = {}
    for snapshot in snapshots:
        key = (snapshot.account.key, snapshot.instrument.key)
        current = latest.get(key)
        if current is None or (snapshot.observed_at, snapshot.source.key) > (
            current.observed_at,
            current.source.key,
        ):
            latest[key] = snapshot
    return {key: snapshot.quantity for key, snapshot in latest.items()}


def reconcile_positions(
    events: list[LedgerEvent], snapshots: list[BrokerPositionSnapshot]
) -> tuple[ReconciliationDifference, ...]:
    return reconcile({}, {}, positions(events), broker_positions(snapshots))


def reconcile_cash(
    events: list[LedgerEvent], observed: dict[tuple[str, Currency], Decimal]
) -> tuple[ReconciliationDifference, ...]:
    return reconcile(cash_balances(events), observed, {}, {})


def render_discrepancy_report(differences: tuple[ReconciliationDifference, ...]) -> str:
    if not differences:
        return "reconciliation: clean"
    rows = ["reconciliation discrepancies", "subject | expected | observed | delta"]
    rows.extend(
        f"{item.subject} | {item.expected} | {item.observed} | {item.delta}"
        for item in differences
    )
    return "\n".join(rows)
