from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal

from stonks_cli.errors import LedgerError
from stonks_cli.types import EventKind, LedgerEvent


@dataclass(frozen=True)
class OpenLot:
    account_id: str
    instrument_key: str
    quantity: Decimal
    cost: Decimal

    @property
    def unit_cost(self) -> Decimal:
        return self.cost / self.quantity


@dataclass(frozen=True)
class RealizedPnL:
    fingerprint: str
    proceeds: Decimal
    cost: Decimal

    @property
    def value(self) -> Decimal:
        return self.proceeds - self.cost


def fifo_lots(events: list[LedgerEvent]) -> tuple[tuple[OpenLot, ...], tuple[RealizedPnL, ...]]:
    lots: dict[tuple[str, str], deque[OpenLot]] = defaultdict(deque)
    realized: list[RealizedPnL] = []
    for event in sorted(events, key=lambda item: (item.occurred_at, item.fingerprint)):
        if event.kind not in {EventKind.BUY, EventKind.SELL, EventKind.SPLIT}:
            continue
        if event.instrument is None:
            raise LedgerError(f"instrument required for accounting:{event.fingerprint}")
        key = (event.account_id, event.instrument.key)
        if event.kind is EventKind.BUY:
            lots[key].append(
                OpenLot(
                    event.account_id, event.instrument.key, event.quantity, event.amount + event.fee
                )
            )
        elif event.kind is EventKind.SPLIT:
            lots[key] = deque(
                OpenLot(lot.account_id, lot.instrument_key, lot.quantity * event.quantity, lot.cost)
                for lot in lots[key]
            )
        else:
            remaining = event.quantity
            cost = Decimal("0")
            while remaining > 0 and lots[key]:
                lot = lots[key].popleft()
                consumed = min(remaining, lot.quantity)
                consumed_cost = lot.cost * consumed / lot.quantity
                cost += consumed_cost
                residual = lot.quantity - consumed
                if residual > 0:
                    lots[key].appendleft(
                        OpenLot(
                            lot.account_id, lot.instrument_key, residual, lot.cost - consumed_cost
                        )
                    )
                remaining -= consumed
            if remaining > 0:
                raise LedgerError(f"sell exceeds FIFO position:{event.fingerprint}")
            realized.append(RealizedPnL(event.fingerprint, event.amount - event.fee, cost))
    return tuple(lot for queue in lots.values() for lot in queue), tuple(realized)


def unrealized_pnl(lots: tuple[OpenLot, ...], prices: dict[str, Decimal]) -> Decimal:
    total = Decimal("0")
    for lot in lots:
        if lot.instrument_key not in prices:
            continue
        total += lot.quantity * prices[lot.instrument_key] - lot.cost
    return total
