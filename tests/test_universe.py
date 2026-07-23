from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from stonks_cli.config import EODUniverseSettings, ProfileConfig
from stonks_cli.market_data import (
    DailyPrice,
    FxRate,
    MarketSession,
    QuoteQuality,
    QuoteSnapshot,
    QuoteStatus,
)
from stonks_cli.storage import EncryptedLedger, generate_key_file
from stonks_cli.types import (
    Account,
    AssetClass,
    Currency,
    Instrument,
    InstrumentMaster,
    ListingStatus,
    MoomooInstrumentEligibility,
)
from stonks_cli.universe import (
    DailyLiquidity,
    evaluate_eod_universe,
    import_daily_liquidity_csv,
    latest_daily_liquidity,
)


def test_eod_universe_includes_only_source_backed_cash_eligible_liquid_instruments() -> None:
    account = Account("moomoo", "selected")
    instrument = InstrumentMaster(
        "US:ABC",
        "NASDAQ",
        "US",
        Currency.USD,
        AssetClass.EQUITY,
        "US.ABC",
        ListingStatus.LISTED,
        "provider-1",
        "a" * 64,
    )
    session = date(2026, 1, 20)
    price = DailyPrice(Instrument("ABC", "US", Currency.USD), session, Decimal("10"), "b" * 64)
    eligibility = MoomooInstrumentEligibility(
        "US:ABC", account, datetime(2026, 1, 20, tzinfo=UTC), "c" * 64, True, True, True
    )
    liquidity = tuple(
        DailyLiquidity(
            "US:ABC",
            session - timedelta(days=index),
            Decimal("500000"),
            Currency.USD,
            "d" * 64,
            datetime.combine(session - timedelta(days=index), datetime.min.time(), tzinfo=UTC),
            "provider",
        )
        for index in range(15)
    )
    quote = QuoteSnapshot(
        Instrument("ABC", "US", Currency.USD),
        Decimal("10"),
        datetime(2026, 1, 20, 12, tzinfo=UTC),
        QuoteQuality.REAL_TIME,
        "e" * 64,
        status=QuoteStatus.AVAILABLE,
        as_of_at=datetime(2026, 1, 20, 12, tzinfo=UTC),
        bid_price=Decimal("9.99"),
        ask_price=Decimal("10.01"),
        midpoint=Decimal("10"),
        spread=Decimal("0.02"),
        order_book_as_of=datetime(2026, 1, 20, 12, tzinfo=UTC),
        order_book_status="available",
        market_session=MarketSession.REGULAR,
    )
    rates = {
        item.session_date: {
            (Currency.USD, Currency.SGD): FxRate(
                Currency.USD, Currency.SGD, item.session_date, "1.35", "f" * 64
            )
        }
        for item in liquidity
    }
    rates[session] = {(Currency.USD, Currency.SGD): FxRate(Currency.USD, Currency.SGD, session, "1.35", "f" * 64)}

    decision = evaluate_eod_universe(
        (instrument,),
        {"US:ABC": eligibility},
        account,
        {"US:ABC": price},
        {"US:ABC": liquidity},
        {"US:ABC": quote},
        rates,
        EODUniverseSettings(version=4),
    )[0]

    assert decision.included is True
    assert decision.reasons == ()
    assert decision.configuration_version == 4
    assert decision.price == price
    assert len(decision.liquidity) == 15
    assert len(decision.fx_rates) == 15
    assert decision.quote == quote


def test_eod_universe_excludes_missing_or_unsuitable_filter_inputs() -> None:
    account = Account("moomoo", "selected")
    instrument = InstrumentMaster(
        "US:ABC",
        "NASDAQ",
        "US",
        Currency.USD,
        AssetClass.EQUITY,
        "US.ABC",
        ListingStatus.LISTED,
        "provider-1",
        "a" * 64,
        leveraged=True,
    )

    decision = evaluate_eod_universe(
        (instrument,), {}, account, {}, {}, {}, {}, EODUniverseSettings()
    )[0]

    assert decision.included is False
    assert decision.reasons == (
        "restricted_instrument",
        "missing_cash_eligibility",
        "missing_daily_price",
        "insufficient_liquidity_sessions",
        "missing_quote",
    )


def test_daily_liquidity_import_is_encrypted_and_retains_source_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    source = tmp_path / "liquidity.csv"
    source.write_text(
        "date,identifier,currency,traded_value,as_of_at,provider_id\n"
        "2026-01-02,US:ABC,USD,500000,2026-01-02T12:00:00+00:00,provider\n"
    )

    assert import_daily_liquidity_csv(ledger, source) == 1
    observed = latest_daily_liquidity(ledger)["US:ABC"][0]

    assert observed.traded_value == Decimal("500000")
    assert observed.as_of_at == datetime(2026, 1, 2, 12, tzinfo=UTC)
    assert observed.provider_id == "provider"
    assert b"traded_value" not in ledger.path.read_bytes()
