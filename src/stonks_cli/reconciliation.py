from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stonks_cli.types import Currency


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
