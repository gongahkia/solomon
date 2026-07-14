from __future__ import annotations

import math
import re
from dataclasses import dataclass

from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, ReviewedOrderTicket

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


@dataclass(frozen=True)
class PaperPortfolioPosition:
    symbol: str
    quantity: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("paper portfolio position symbol is invalid")
        if not isinstance(self.quantity, float) or not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("paper portfolio position quantity is invalid")


@dataclass(frozen=True)
class PaperPortfolioAccount:
    account_id: str
    currency: str
    cash_balance: float
    positions: tuple[PaperPortfolioPosition, ...]
    applied_ticket_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("paper portfolio account ID is invalid")
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("paper portfolio account currency is invalid")
        if not isinstance(self.cash_balance, float) or not math.isfinite(self.cash_balance) or self.cash_balance < 0:
            raise ValueError("paper portfolio cash balance is invalid")
        if not isinstance(self.positions, tuple) or not all(isinstance(position, PaperPortfolioPosition) for position in self.positions):
            raise ValueError("paper portfolio positions are invalid")
        symbols = tuple(position.symbol for position in self.positions)
        if len(set(symbols)) != len(symbols) or symbols != tuple(sorted(symbols)):
            raise ValueError("paper portfolio positions are not canonical")
        if not isinstance(self.applied_ticket_ids, tuple) or not all(isinstance(ticket_id, str) and ticket_id for ticket_id in self.applied_ticket_ids):
            raise ValueError("paper portfolio applied ticket IDs are invalid")
        if len(set(self.applied_ticket_ids)) != len(self.applied_ticket_ids) or self.applied_ticket_ids != tuple(sorted(self.applied_ticket_ids)):
            raise ValueError("paper portfolio applied ticket IDs are not canonical")


def run_paper_portfolio_accounting(
    account: PaperPortfolioAccount, tickets: tuple[ReviewedOrderTicket, ...]
) -> PaperPortfolioAccount:
    if not isinstance(account, PaperPortfolioAccount):
        raise TypeError("paper portfolio accounting requires an account")
    if not isinstance(tickets, tuple) or not all(isinstance(ticket, ReviewedOrderTicket) for ticket in tickets):
        raise ValueError("paper portfolio tickets are invalid")
    ticket_ids = tuple(ticket.ticket_id for ticket in tickets)
    if len(set(ticket_ids)) != len(ticket_ids) or tickets != tuple(sorted(tickets, key=lambda ticket: (ticket.reviewed_at, ticket.ticket_id))):
        raise ValueError("paper portfolio tickets are not canonical")
    if set(ticket_ids) & set(account.applied_ticket_ids):
        raise ValueError("paper portfolio ticket was already applied")
    quantities = {position.symbol: position.quantity for position in account.positions}
    cash_balance = account.cash_balance
    for ticket in tickets:
        if ticket.account_id != account.account_id or ticket.currency != account.currency:
            raise ValueError("paper portfolio ticket is incompatible with account")
        notional = ticket.quantity * ticket.limit_price
        if not math.isfinite(notional):
            raise ValueError("paper portfolio ticket notional overflowed")
        if ticket.side is OrderTicketSide.BUY:
            if notional > cash_balance and not math.isclose(notional, cash_balance, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("paper portfolio cash is insufficient")
            cash_balance = math.fsum((cash_balance, -notional))
            quantities[ticket.symbol] = math.fsum((quantities.get(ticket.symbol, 0.0), ticket.quantity))
        else:
            quantity = quantities.get(ticket.symbol)
            if quantity is None or ticket.quantity > quantity and not math.isclose(ticket.quantity, quantity, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("paper portfolio position is insufficient")
            remaining = math.fsum((quantity, -ticket.quantity))
            cash_balance = math.fsum((cash_balance, notional))
            if math.isclose(remaining, 0.0, rel_tol=0.0, abs_tol=1e-12):
                del quantities[ticket.symbol]
            else:
                quantities[ticket.symbol] = remaining
        if not math.isfinite(cash_balance) or not all(math.isfinite(quantity) and quantity > 0 for quantity in quantities.values()):
            raise ValueError("paper portfolio accounting overflowed")
    return PaperPortfolioAccount(
        account.account_id,
        account.currency,
        0.0 if math.isclose(cash_balance, 0.0, rel_tol=0.0, abs_tol=1e-12) else cash_balance,
        tuple(PaperPortfolioPosition(symbol, quantity) for symbol, quantity in sorted(quantities.items())),
        tuple(sorted((*account.applied_ticket_ids, *ticket_ids))),
    )
