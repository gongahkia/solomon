from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stonks_cli.types import (
    Account,
    Currency,
    EventKind,
    EventLifecycle,
    Instrument,
    LedgerEvent,
    SourceProvenance,
    decimal,
)


def test_money_uses_exact_decimal_values_and_supported_currencies() -> None:
    assert decimal("12.340") == Decimal("12.340")
    assert decimal(7) == Decimal("7")
    assert {currency.value for currency in Currency} == {"SGD", "USD"}


@pytest.mark.parametrize("value", ("NaN", "Infinity", "not-money"))
def test_money_rejects_non_finite_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        decimal(value)


def test_instrument_identity_is_trimmed_and_canonicalized() -> None:
    instrument = Instrument(" spy ", " us ", Currency.USD, "S&P 500 ETF")
    assert instrument.symbol == "SPY"
    assert instrument.market == "US"
    assert instrument.key == "US:SPY"


@pytest.mark.parametrize("symbol,market", (("", "US"), ("SPY", " ")))
def test_instrument_identity_requires_symbol_and_market(symbol: str, market: str) -> None:
    with pytest.raises(ValueError, match="required"):
        Instrument(symbol, market, Currency.USD)


def test_account_identity_is_provider_qualified_and_canonicalized() -> None:
    account = Account(" Moomoo ", " 123 ", "Personal")
    assert account.provider_id == "moomoo"
    assert account.account_id == "123"
    assert account.key == "moomoo:123"


@pytest.mark.parametrize("provider_id,account_id", (("", "123"), ("csv", "  ")))
def test_account_identity_requires_provider_and_identifier(
    provider_id: str, account_id: str
) -> None:
    with pytest.raises(ValueError, match="required"):
        Account(provider_id, account_id)


def test_source_provenance_is_immutable_and_canonicalized() -> None:
    provenance = SourceProvenance(" CSV ", "A" * 64, " line-7 ")
    assert provenance.provider_id == "csv"
    assert provenance.source_hash == "a" * 64
    assert provenance.record_id == "line-7"
    assert provenance.key == f"csv:{'a' * 64}:line-7"


@pytest.mark.parametrize("source_hash", ("short", "g" * 64))
def test_source_provenance_requires_sha256_digest(source_hash: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        SourceProvenance("csv", source_hash, "line-1")


def test_ledger_event_uses_canonical_source_and_account_identities() -> None:
    source = SourceProvenance(" CSV ", "A" * 64, " row-1 ")
    account = Account(" Moomoo ", " 123 ", "Personal")
    event = LedgerEvent(
        fingerprint=" event-1 ",
        source=source,
        account=account,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("100"),
    )

    assert event.fingerprint == "event-1"
    assert event.source_id == f"csv:{'a' * 64}:row-1"
    assert event.account_id == "moomoo:123"
    assert event.to_data()["source"] == {
        "provider_id": "csv",
        "source_hash": "a" * 64,
        "record_id": "row-1",
    }
    assert event.to_data()["account"] == {
        "provider_id": "moomoo",
        "account_id": "123",
        "name": "Personal",
    }


@pytest.mark.parametrize(
    ("amount", "quantity", "fee"),
    (("0", "0", "0"), ("100", "1", "0"), ("100", "0", "1")),
)
def test_cash_transfers_reject_non_cash_payloads(amount: str, quantity: str, fee: str) -> None:
    with pytest.raises(ValueError, match="cash transfers"):
        LedgerEvent(
            fingerprint="event-1",
            source=SourceProvenance("csv", "a" * 64, "1"),
            account=Account("csv", "main"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            kind=EventKind.CASH_DEPOSIT,
            currency=Currency.USD,
            amount=Decimal(amount),
            quantity=Decimal(quantity),
            fee=Decimal(fee),
        )


@pytest.mark.parametrize("kind", (EventKind.BUY, EventKind.SELL))
def test_trade_fills_require_positive_consideration(kind: EventKind) -> None:
    with pytest.raises(ValueError, match="positive amount"):
        LedgerEvent(
            fingerprint=f"{kind.value}-event",
            source=SourceProvenance("csv", "a" * 64, kind.value),
            account=Account("csv", "main"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            kind=kind,
            currency=Currency.USD,
            amount=Decimal("0"),
            quantity=Decimal("1"),
            instrument=Instrument("SPY", "US", Currency.USD),
        )


@pytest.mark.parametrize(
    ("amount", "quantity", "fee"),
    (("0", "0", "0"), ("5", "1", "0"), ("5", "0", "1")),
)
def test_fee_events_reject_non_fee_payloads(amount: str, quantity: str, fee: str) -> None:
    with pytest.raises(ValueError, match="fee events"):
        LedgerEvent(
            fingerprint="fee-event",
            source=SourceProvenance("csv", "a" * 64, "fee"),
            account=Account("csv", "main"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            kind=EventKind.FEE,
            currency=Currency.USD,
            amount=Decimal(amount),
            quantity=Decimal(quantity),
            fee=Decimal(fee),
        )


@pytest.mark.parametrize(
    ("amount", "instrument", "fee"),
    (("0", Instrument("SPY", "US", Currency.USD), "0"), ("3", None, "0"), ("3", Instrument("SPY", "US", Currency.USD), "1")),
)
def test_dividend_events_require_instrument_cash_payload(
    amount: str, instrument: Instrument | None, fee: str
) -> None:
    with pytest.raises(ValueError, match="dividend"):
        LedgerEvent(
            fingerprint="dividend-event",
            source=SourceProvenance("csv", "a" * 64, "dividend"),
            account=Account("csv", "main"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            kind=EventKind.DIVIDEND,
            currency=Currency.USD,
            amount=Decimal(amount),
            instrument=instrument,
            fee=Decimal(fee),
        )


@pytest.mark.parametrize(
    ("source", "account"),
    (
        (None, Account("csv", "1")),
        (SourceProvenance("csv", "a" * 64, "1"), None),
    ),
)
def test_ledger_event_requires_canonical_source_and_account(source, account) -> None:
    with pytest.raises(ValueError, match="source and account"):
        LedgerEvent(
            fingerprint="event-1",
            source=source,
            account=account,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            kind=EventKind.CASH_DEPOSIT,
            currency=Currency.USD,
            amount=Decimal("100"),
        )


def test_ledger_event_models_immutable_corrections_and_reversals() -> None:
    source = SourceProvenance("csv", "a" * 64, "row-2")
    account = Account("csv", "main")
    correction = LedgerEvent(
        fingerprint="event-2",
        source=source,
        account=account,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        kind=EventKind.CASH_DEPOSIT,
        currency=Currency.USD,
        amount=Decimal("100"),
        lifecycle=EventLifecycle.CORRECTION,
        corrects_fingerprint=" event-1 ",
    )
    reversal = LedgerEvent(
        fingerprint="event-3",
        source=source,
        account=account,
        occurred_at=datetime(2026, 1, 3, tzinfo=UTC),
        kind=EventKind.CASH_WITHDRAWAL,
        currency=Currency.USD,
        amount=Decimal("100"),
        lifecycle=EventLifecycle.REVERSAL,
        corrects_fingerprint="event-2",
    )

    assert correction.corrects_fingerprint == "event-1"
    assert correction.to_data()["lifecycle"] == "correction"
    assert reversal.lifecycle is EventLifecycle.REVERSAL


@pytest.mark.parametrize(
    ("lifecycle", "corrects_fingerprint", "error"),
    (
        (EventLifecycle.POSTED, "event-1", "posted events"),
        (EventLifecycle.CORRECTION, None, "target fingerprint"),
        (EventLifecycle.REVERSAL, "event-1", "cannot correct themselves"),
    ),
)
def test_ledger_event_rejects_invalid_lifecycle_transitions(
    lifecycle: EventLifecycle, corrects_fingerprint: str | None, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        LedgerEvent(
            fingerprint="event-1",
            source=SourceProvenance("csv", "a" * 64, "row-2"),
            account=Account("csv", "main"),
            occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
            kind=EventKind.CASH_DEPOSIT,
            currency=Currency.USD,
            amount=Decimal("100"),
            lifecycle=lifecycle,
            corrects_fingerprint=corrects_fingerprint,
        )
