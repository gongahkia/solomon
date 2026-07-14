from __future__ import annotations

from stonks_cli.vnext.moomoo import MoomooInstrument
from stonks_cli.vnext.reviewed_order_ticket import ReviewedOrderTicket


def validate_exchange_lot_size(ticket: ReviewedOrderTicket, instruments: tuple[MoomooInstrument, ...]) -> None:
    if not isinstance(ticket, ReviewedOrderTicket):
        raise TypeError("exchange lot-size validation requires a reviewed order ticket")
    if not isinstance(instruments, tuple) or not instruments or not all(isinstance(instrument, MoomooInstrument) for instrument in instruments):
        raise ValueError("exchange lot-size instruments are invalid")
    symbols = tuple(instrument.symbol for instrument in instruments)
    if len(set(symbols)) != len(symbols) or symbols != tuple(sorted(symbols)):
        raise ValueError("exchange lot-size instruments are not canonical")
    instrument = next((item for item in instruments if item.symbol == ticket.symbol), None)
    if instrument is None:
        raise ValueError(f"exchange lot-size instrument is missing:{ticket.symbol}")
    if instrument.suspended:
        raise ValueError(f"exchange lot-size instrument is suspended:{ticket.symbol}")
    if not (ticket.quantity / instrument.lot_size).is_integer():
        raise ValueError(f"exchange lot-size quantity is not an integral lot:{ticket.symbol}")
