from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import pytest
from conftest import encrypted_ledger

from stonks_cli.errors import ProviderError
from stonks_cli.ledger import (
    list_cash_flows,
    list_cash_snapshots,
    list_dividend_declarations,
    list_events,
    list_position_snapshots,
)
from stonks_cli.moomoo import (
    MoomooRateLimiter,
    MoomooReadOnlyProvider,
    OpenDConnection,
    OpenDSDKStatus,
    import_account_snapshot,
    import_cash_flows,
    import_dividend_declarations,
    import_order_fees,
    import_stock_splits,
)
from stonks_cli.types import Account, Currency, EventKind, Instrument


class Context:
    def __init__(self) -> None:
        self.closed = False

    def get_acc_list(self):
        return 0, [{"acc_id": 2, "acc_index": 1, "trd_env": "REAL"}]

    def accinfo_query(self, **kwargs):
        assert kwargs == {"acc_id": "2"}
        return 0, [{"cash": 100}]

    def get_acc_cash_flow(self, **kwargs):
        assert kwargs == {"acc_id": "2", "clearing_date": "2026-07-22"}
        return 0, [{"cashflow_id": "1"}]

    def position_list_query(self, **kwargs):
        assert kwargs == {"acc_id": "2"}
        return 0, [{"code": "US.SPY"}]

    def history_order_list_query(self, **kwargs):
        assert kwargs == {"acc_id": "2", "start": "2026-01-01", "end": "2026-01-02"}
        return 0, [{"order_id": "1"}]

    def history_deal_list_query(self, **kwargs):
        assert kwargs == {"acc_id": "2", "start": "2026-01-01", "end": "2026-01-02"}
        return 0, [{"deal_id": "1"}]

    def order_fee_query(self, order_ids):
        assert order_ids == ("o-1",)
        return 0, [{"order_id": "o-1", "fee_amount": "1", "fee_details": [("Commission", "1")]}]

    def close(self) -> None:
        self.closed = True


class AccountContext(Context):
    def __init__(self, records: object) -> None:
        super().__init__()
        self.records = records

    def get_acc_list(self):
        return 0, self.records


class QuoteContext:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        if kwargs["page_req_key"] is None:
            return 0, [{"time_key": "2026-01-01 00:00:00", "close": "100"}], b"page-2"
        return 0, [{"time_key": "2026-01-02 00:00:00", "close": "101"}], None

    def close(self) -> None:
        self.closed = True


class RepeatingPageQuoteContext(QuoteContext):
    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        return 0, [{"time_key": "2026-01-01 00:00:00", "close": "100"}], b"same-page"


class EndlessPageQuoteContext(QuoteContext):
    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        return 0, [{"time_key": "2026-01-01 00:00:00", "close": "100"}], str(len(self.calls))


class OversizedPageQuoteContext(QuoteContext):
    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        return (
            0,
            [
                {"time_key": "2026-01-01 00:00:00", "close": "100"},
                {"time_key": "2026-01-02 00:00:00", "close": "101"},
            ],
            None,
        )


class InvalidTokenQuoteContext(QuoteContext):
    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        return 0, [{"time_key": "2026-01-01 00:00:00", "close": "100"}], 1


class SnapshotQuoteContext:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        *,
        response_code: int = 0,
        market_state: dict[str, object] | None = None,
    ) -> None:
        self.closed = False
        self.codes: list[list[str]] = []
        self.subscribe_calls: list[tuple[object, ...]] = []
        self.rows = rows
        self.response_code = response_code
        self.market_state = market_state or {}

    def get_market_snapshot(self, codes: list[str]):
        self.codes.append(codes)
        if self.rows is not None:
            return self.response_code, self.rows
        return self.response_code, [
            {
                "code": code,
                "last_price": "100",
                "update_time": "2026-01-02 09:30:00",
                "quote_status": "ENTITLED",
                "bid_price": "99.90",
                "ask_price": "100.10",
            }
            for code in codes
        ]

    def get_global_state(self):
        return 0, self.market_state

    def subscribe(self, *args: object) -> tuple[int, object]:
        self.subscribe_calls.append(args)
        return 0, None

    def close(self) -> None:
        self.closed = True


class SplitQuoteContext:
    def __init__(self, next_keys: tuple[str, ...] = ("-1",)) -> None:
        self.closed = False
        self.calls: list[dict[str, object]] = []
        self.next_keys = iter(next_keys)

    def get_corporate_actions_stock_splits(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        return 0, {
            "next_key": next(self.next_keys),
            "split_list": [{"reform_type": "Split", "rate": "1->5", "dir_deci_pub_date_str": "2026-01-02"}],
        }

    def close(self) -> None:
        self.closed = True


def _opend_fixture() -> dict[str, object]:
    path = Path(__file__).parent / "fixtures" / "moomoo" / "opend_responses.json"
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    return payload


class FixtureContext:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.closed = False

    def get_acc_list(self):
        return 0, self.payload["accounts"]

    def accinfo_query(self, **kwargs):
        assert kwargs == {"acc_id": "900001"}
        return 0, self.payload["balances"]

    def get_acc_cash_flow(self, **kwargs):
        assert kwargs == {"acc_id": "900001", "clearing_date": "2026-01-02"}
        return 0, self.payload["cash_flows"]

    def position_list_query(self, **kwargs):
        assert kwargs == {"acc_id": "900001"}
        return 0, self.payload["positions"]

    def history_order_list_query(self, **kwargs):
        assert kwargs == {"acc_id": "900001", "start": "2026-01-01", "end": "2026-01-02"}
        return 0, self.payload["orders"]

    def history_deal_list_query(self, **kwargs):
        assert kwargs == {"acc_id": "900001", "start": "2026-01-01", "end": "2026-01-02"}
        return 0, self.payload["fills"]

    def order_fee_query(self, order_ids):
        assert order_ids == ("order-001",)
        return 0, self.payload["order_fees"]

    def close(self) -> None:
        self.closed = True


class FixtureQuoteContext:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.closed = False

    def request_history_kline(self, code: str, **kwargs):
        assert code == "US.SYNTH"
        page = 0 if kwargs["page_req_key"] is None else 1
        return 0, self.payload["daily_pages"][page], None if page else "page-2"

    def get_market_snapshot(self, codes: list[str]):
        assert codes == ["US.SYNTH"]
        return 0, self.payload["market_snapshots"]

    def get_corporate_actions_stock_splits(self, code: str, **kwargs):
        assert code == "US.SYNTH"
        assert kwargs == {"next_key": None, "num": 50}
        return 0, self.payload["stock_splits"]

    def get_corporate_actions_dividends(self, code: str):
        assert code == "US.SYNTH"
        return 0, self.payload["dividends"]

    def close(self) -> None:
        self.closed = True


def test_moomoo_reads_accounts_from_loopback_context() -> None:
    contexts: list[Context] = []

    def factory(_: str, __: int) -> Context:
        context = Context()
        contexts.append(context)
        return context

    accounts = MoomooReadOnlyProvider(OpenDConnection(), factory).accounts()
    assert accounts[0].account_id == "2"
    assert contexts[0].closed is True


def test_moomoo_requires_explicit_current_account_selection() -> None:
    provider = MoomooReadOnlyProvider(OpenDConnection(), lambda _host, _port: Context())

    assert provider.selected_account(" 2 ").environment == "REAL"
    for account_id in ("", "missing"):
        with pytest.raises(ProviderError, match="selection"):
            provider.selected_account(account_id)


@pytest.mark.parametrize(
    "records",
    (
        [{"acc_id": " ", "acc_index": 0, "trd_env": "REAL"}],
        [{"acc_id": "1", "acc_index": -1, "trd_env": "REAL"}],
        [{"acc_id": "1", "acc_index": True, "trd_env": "REAL"}],
        [{"acc_id": "1", "acc_index": 0, "trd_env": " "}],
        [
            {"acc_id": "1", "acc_index": 0, "trd_env": "REAL"},
            {"acc_id": "1", "acc_index": 1, "trd_env": "PAPER"},
        ],
    ),
)
def test_moomoo_rejects_malformed_account_rows(records: object) -> None:
    context = AccountContext(records)
    provider = MoomooReadOnlyProvider(OpenDConnection(), lambda _host, _port: context)

    with pytest.raises(ProviderError, match="Moomoo account"):
        provider.accounts()

    assert context.closed is True


def test_moomoo_rejects_non_loopback_endpoint() -> None:
    try:
        OpenDConnection("10.0.0.1", 11111)
    except Exception as error:
        assert "loopback" in str(error)
    else:
        raise AssertionError("non-loopback endpoint must be rejected")


@pytest.mark.parametrize("port", (0, 65536, True, "11111"))
def test_moomoo_rejects_invalid_loopback_ports(port: object) -> None:
    with pytest.raises(ProviderError, match="loopback"):
        OpenDConnection("localhost", port)  # type: ignore[arg-type]


def test_moomoo_rejects_non_string_loopback_host() -> None:
    with pytest.raises(ProviderError, match="loopback"):
        OpenDConnection(None, 11111)  # type: ignore[arg-type]


def test_moomoo_reads_documented_account_data_only() -> None:
    provider = MoomooReadOnlyProvider(OpenDConnection(), lambda _host, _port: Context())

    assert provider.balances("2") == ({"cash": 100},)
    assert provider.cash_flows("2", "2026-07-22") == ({"cashflow_id": "1"},)
    assert provider.positions("2") == ({"code": "US.SPY"},)
    assert provider.historical_orders("2", "2026-01-01", "2026-01-02") == ({"order_id": "1"},)
    assert provider.historical_fills("2", "2026-01-01", "2026-01-02") == ({"deal_id": "1"},)
    assert provider.order_fees("2", ("o-1",)) == (
        {"order_id": "o-1", "fee_amount": "1", "fee_details": [("Commission", "1")]},
    )


def test_moomoo_synthetic_opend_fixture_suite() -> None:
    payload = _opend_fixture()
    provider = MoomooReadOnlyProvider(
        OpenDConnection(),
        lambda _host, _port: FixtureContext(payload),
        lambda _host, _port: FixtureQuoteContext(payload),
    )
    instrument = Instrument("SYNTH", "US", Currency.USD)

    assert provider.accounts()[0].account_id == "900001"
    assert provider.balances("900001") == ({"us_cash": "1234.56", "sg_cash": "78.90"},)
    assert provider.cash_flows("900001", "2026-01-02") == (
        {"cashflow_id": "flow-001", "cashflow_type": "Others"},
    )
    assert provider.positions("900001") == ({"code": "US.SYNTH"},)
    assert provider.historical_orders("900001", "2026-01-01", "2026-01-02") == ({"order_id": "order-001"},)
    assert provider.historical_fills("900001", "2026-01-01", "2026-01-02") == ({"deal_id": "deal-001"},)
    assert provider.order_fees("900001", ("order-001",))[0]["fee_amount"] == "1.00"
    assert [price.close for price in provider.daily_prices((instrument,), date(2026, 1, 1), date(2026, 1, 2))] == [Decimal("100"), Decimal("101")]
    assert provider.market_snapshots((instrument,), datetime(2026, 1, 2, 21, 1, tzinfo=UTC))[0].last_price == Decimal("101")
    assert provider.corporate_splits(instrument)[0]["rate"] == "1->2"
    assert provider.corporate_dividends(instrument)[0]["process"] == "Proposed"


def test_moomoo_rejects_unknown_and_execution_methods() -> None:
    provider = MoomooReadOnlyProvider(OpenDConnection(), lambda _host, _port: Context())

    for method in ("unlock_trade", "place_order", "modify_order", "order_list_query", "unknown"):
        try:
            provider._call(method)
        except Exception as error:
            assert "not read-only" in str(error)
        else:
            raise AssertionError(f"{method} must be rejected")


def test_moomoo_probe_reports_only_local_readiness(monkeypatch) -> None:
    contexts: list[Context] = []

    def factory(_host: str, _port: int) -> Context:
        context = Context()
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(OpenDConnection(), factory)
    monkeypatch.setattr(MoomooReadOnlyProvider, "from_installed_sdk", lambda _endpoint: provider)
    monkeypatch.setattr(
        MoomooReadOnlyProvider,
        "sdk_status",
        staticmethod(lambda: OpenDSDKStatus(True, "10.9", None)),
    )

    probe = MoomooReadOnlyProvider.probe(OpenDConnection())

    assert probe.sdk_version == "10.9"
    assert probe.account_count == 1
    assert probe.endpoint == OpenDConnection()
    assert contexts[0].closed is True
    assert "account_id" not in probe.__dict__


@pytest.mark.parametrize(
    ("version", "module", "available", "reason"),
    (
        (None, object(), False, "distribution_missing"),
        ("10.9", None, False, "module_missing"),
        ("latest", object(), False, "version_malformed"),
        ("9.9", object(), False, "version_incompatible"),
        ("11.0", object(), False, "version_incompatible"),
        ("10.9.1", object(), True, None),
    ),
)
def test_moomoo_sdk_status_requires_compatible_distribution_and_module(
    monkeypatch, version: str | None, module: object | None, available: bool, reason: str | None
) -> None:
    if version is None:
        monkeypatch.setattr(
            "stonks_cli.moomoo.metadata.version",
            lambda _name: (_ for _ in ()).throw(metadata.PackageNotFoundError("moomoo-api")),
        )
    else:
        monkeypatch.setattr("stonks_cli.moomoo.metadata.version", lambda _name: version)
    monkeypatch.setattr("stonks_cli.moomoo.util.find_spec", lambda _name: module)

    status = MoomooReadOnlyProvider.sdk_status()

    assert status == OpenDSDKStatus(available, version, reason)


def test_moomoo_reads_paginated_daily_bars_from_local_quote_context() -> None:
    contexts: list[QuoteContext] = []

    def quote_factory(_host: str, _port: int) -> QuoteContext:
        context = QuoteContext()
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), quote_factory
    )
    instrument = Instrument("SPY", "US", Currency.USD)

    prices = provider.daily_prices((instrument,), date(2026, 1, 1), date(2026, 1, 2))

    assert [item.close for item in prices] == [Decimal("100"), Decimal("101")]
    assert contexts[0].calls[0]["code"] == "US.SPY"
    assert contexts[0].calls[1]["page_req_key"] == b"page-2"
    assert contexts[0].closed is True


@pytest.mark.parametrize(
    ("context_type", "error"),
    (
        (RepeatingPageQuoteContext, "repeated page key"),
        (InvalidTokenQuoteContext, "token is invalid"),
    ),
)
def test_moomoo_historical_pagination_rejects_invalid_continuations(
    context_type: type[QuoteContext], error: str
) -> None:
    contexts: list[QuoteContext] = []

    def quote_factory(_host: str, _port: int) -> QuoteContext:
        context = context_type()
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), quote_factory
    )

    with pytest.raises(ProviderError, match=error):
        provider.daily_prices(
            (Instrument("SPY", "US", Currency.USD),), date(2026, 1, 1), date(2026, 1, 2)
        )

    assert contexts[0].closed is True


def test_moomoo_historical_pagination_enforces_page_and_row_bounds(monkeypatch) -> None:
    page_contexts: list[EndlessPageQuoteContext] = []

    def page_factory(_host: str, _port: int) -> EndlessPageQuoteContext:
        context = EndlessPageQuoteContext()
        page_contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), page_factory
    )
    monkeypatch.setattr("stonks_cli.moomoo._MAX_HISTORICAL_PAGES", 2)

    with pytest.raises(ProviderError, match="page limit"):
        provider.daily_prices(
            (Instrument("SPY", "US", Currency.USD),), date(2026, 1, 1), date(2026, 1, 2)
        )

    assert len(page_contexts[0].calls) == 2
    assert page_contexts[0].closed is True

    row_contexts: list[OversizedPageQuoteContext] = []

    def row_factory(_host: str, _port: int) -> OversizedPageQuoteContext:
        context = OversizedPageQuoteContext()
        row_contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), row_factory
    )
    monkeypatch.setattr("stonks_cli.moomoo._MAX_HISTORICAL_ROWS", 1)

    with pytest.raises(ProviderError, match="row limit"):
        provider.daily_prices(
            (Instrument("SPY", "US", Currency.USD),), date(2026, 1, 1), date(2026, 1, 2)
        )

    assert row_contexts[0].closed is True


def test_moomoo_market_snapshots_capture_entitled_bid_ask_without_subscription() -> None:
    contexts: list[SnapshotQuoteContext] = []

    def quote_factory(_host: str, _port: int) -> SnapshotQuoteContext:
        context = SnapshotQuoteContext()
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), quote_factory
    )
    snapshots = provider.market_snapshots(
        (Instrument("SPY", "US", Currency.USD),), datetime(2026, 1, 2, 14, 31, tzinfo=UTC)
    )

    assert snapshots[0].quality.value == "real_time"
    assert snapshots[0].status.value == "available"
    assert snapshots[0].current_price == Decimal("100")
    assert snapshots[0].spread == Decimal("0.20")
    assert snapshots[0].subscription_mode == "none"
    assert contexts[0].codes == [["US.SPY"]]
    assert contexts[0].subscribe_calls == []
    assert contexts[0].closed is True


@pytest.mark.parametrize(
    ("fixture_name", "instrument", "observed_at", "expected_status", "expected_current", "expected_book"),
    (
        (
            "entitled_us",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
            "available",
            Decimal("101"),
            "snapshot",
        ),
        (
            "entitled_sg",
            Instrument("SYNTH", "SG", Currency.SGD),
            datetime(2026, 1, 2, 12, 1, tzinfo=UTC),
            "available",
            Decimal("10"),
            "snapshot",
        ),
        (
            "delayed",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
            "delayed",
            None,
            "absent",
        ),
        (
            "unentitled",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
            "unentitled",
            None,
            "absent",
        ),
        (
            "stale",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, tzinfo=UTC),
            "stale",
            None,
            "absent",
        ),
        (
            "malformed",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
            "malformed",
            None,
            "malformed",
        ),
        (
            "absent_order_book",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
            "available",
            Decimal("101"),
            "absent",
        ),
        (
            "excessive_spread",
            Instrument("SYNTH", "US", Currency.USD),
            datetime(2026, 1, 2, 15, 1, tzinfo=UTC),
            "excessive_spread",
            None,
            "snapshot",
        ),
    ),
)
def test_moomoo_quote_snapshot_fixtures_fail_closed(
    fixture_name: str,
    instrument: Instrument,
    observed_at: datetime,
    expected_status: str,
    expected_current: Decimal | None,
    expected_book: str,
) -> None:
    payload = _opend_fixture()
    records = payload["quote_snapshots"]
    assert isinstance(records, dict)
    rows = records[fixture_name]
    assert isinstance(rows, list)
    context = SnapshotQuoteContext(rows, market_state={f"market_{instrument.market.lower()}": "AFTERNOON"})
    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), lambda _host, _port: context
    )

    snapshot = provider.market_snapshots((instrument,), observed_at)[0]

    assert snapshot.status.value == expected_status
    assert snapshot.current_price == expected_current
    assert snapshot.order_book_status == expected_book
    assert snapshot.market_session.value == ("unknown" if expected_status == "malformed" else "regular")
    assert snapshot.market_session_raw == ("unknown" if expected_status == "malformed" else "AFTERNOON")
    assert snapshot.subscription_mode == "none"
    assert context.subscribe_calls == []
    assert context.closed is True


def test_moomoo_quote_unavailable_response_is_persistable_status() -> None:
    payload = _opend_fixture()
    records = payload["quote_snapshots"]
    assert isinstance(records, dict)
    rows = records["unavailable"]
    assert isinstance(rows, list)
    context = SnapshotQuoteContext(rows, response_code=-1)
    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), lambda _host, _port: context
    )

    snapshot = provider.market_snapshots(
        (Instrument("SYNTH", "US", Currency.USD),), datetime(2026, 1, 2, 15, tzinfo=UTC)
    )[0]

    assert snapshot.status.value == "unavailable"
    assert snapshot.current_price is None
    assert context.closed is True


def test_moomoo_normalizes_documented_us_and_sg_market_sessions() -> None:
    instruments = (
        Instrument("SYNTH", "US", Currency.USD),
        Instrument("SYNTH", "SG", Currency.SGD),
    )
    context = SnapshotQuoteContext(
        [
            {
                "code": "US.SYNTH",
                "last_price": "101",
                "update_time": "2026-01-02 10:00:00",
                "quote_status": "ENTITLED",
            },
            {
                "code": "SG.SYNTH",
                "last_price": "10",
                "update_time": "2026-01-02 20:00:00",
                "quote_status": "ENTITLED",
            },
        ],
        market_state={"market_us": "PRE_MARKET_BEGIN", "market_sg": "REST"},
    )
    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), lambda _host, _port: context
    )

    snapshots = provider.market_snapshots(
        instruments, datetime(2026, 1, 2, 15, 1, tzinfo=UTC), maximum_age=timedelta(hours=4)
    )

    assert [(item.instrument.market, item.market_session.value, item.market_session_raw) for item in snapshots] == [
        ("SG", "break", "REST"),
        ("US", "pre_market", "PRE_MARKET_BEGIN"),
    ]


def test_moomoo_reads_paginated_stock_split_records() -> None:
    contexts: list[SplitQuoteContext] = []

    def quote_factory(_host: str, _port: int) -> SplitQuoteContext:
        context = SplitQuoteContext(("next", "-1"))
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), quote_factory
    )

    records = provider.corporate_splits(Instrument("SPY", "US", Currency.USD))

    assert len(records) == 2
    assert contexts[0].calls == [
        {"code": "US.SPY", "next_key": None, "num": 50},
        {"code": "US.SPY", "next_key": "next", "num": 50},
    ]
    assert contexts[0].closed is True


def test_moomoo_stock_split_pagination_rejects_repeated_keys() -> None:
    context = SplitQuoteContext(("next", "next"))
    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), lambda _host, _port: context
    )

    with pytest.raises(ProviderError, match="repeated page key"):
        provider.corporate_splits(Instrument("SPY", "US", Currency.USD))

    assert context.closed is True


def test_moomoo_import_archives_fills_and_observed_account_snapshots(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    result = import_account_snapshot(
        ledger,
        Account("moomoo", "2"),
        fills=(
            {
                "deal_id": "d-1",
                "order_id": "o-1",
                "trd_side": "BUY",
                "code": "US.SPY",
                "stock_name": "SPDR S&P 500 ETF Trust",
                "deal_market": "US",
                "qty": "2",
                "price": "100.5",
                "create_time": "2026-01-02 09:30:00",
            },
        ),
        positions=(
            {
                "position_id": "p-1",
                "code": "US.SPY",
                "position_market": "US",
                "currency": "USD",
                "qty": "2",
                "position_side": "LONG",
            },
        ),
        balances=({"us_cash": "799"},),
        observed_at=datetime(2026, 1, 2, 10, tzinfo=UTC),
        opend_timezone="Asia/Singapore",
    )

    assert result.fills_inserted == 1
    assert result.position_snapshots == 1
    assert result.cash_snapshots == 1
    assert len(result.source_hashes) == 3
    assert all((ledger.sources / f"{source_hash}.enc").is_file() for source_hash in result.source_hashes)
    event = list_events(ledger)[0]
    assert event.kind is EventKind.BUY
    assert event.amount == Decimal("201.0")
    assert event.occurred_at == datetime(2026, 1, 2, 1, 30, tzinfo=UTC)
    assert event.metadata["raw_payload_hash"] != event.source.source_hash
    assert (ledger.sources / f"{event.metadata['raw_payload_hash']}.enc").is_file()
    assert list_position_snapshots(ledger)[0].quantity == Decimal("2")
    assert list_cash_snapshots(ledger)[0].amount == Decimal("799")


def test_moomoo_import_is_idempotent_for_unchanged_vendor_fill(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    arguments = {
        "fills": (
            {
                "deal_id": "d-1",
                "trd_side": "SELL",
                "code": "HK.00700",
                "deal_market": "HK",
                "qty": "1",
                "price": "500",
                "create_time": "2026-01-02 09:30:00",
            },
        ),
        "positions": (),
        "balances": (),
        "observed_at": datetime(2026, 1, 2, tzinfo=UTC),
        "opend_timezone": "Asia/Singapore",
    }

    first = import_account_snapshot(ledger, Account("moomoo", "2"), **arguments)
    second = import_account_snapshot(ledger, Account("moomoo", "2"), **arguments)

    assert (first.fills_inserted, first.fills_skipped) == (1, 0)
    assert (second.fills_inserted, second.fills_skipped) == (0, 1)


def test_moomoo_cash_flows_are_archived_without_ledger_classification(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    records = (
        {
            "cashflow_id": "c-1",
            "clearing_date": "2026-01-02",
            "settlement_date": "2026-01-03",
            "currency": "USD",
            "cashflow_type": "Fund Redemption",
            "cashflow_direction": "IN",
            "cashflow_amount": "12.5",
            "cashflow_remark": "example",
        },
    )

    assert import_cash_flows(ledger, Account("moomoo", "2"), records) == (1, 0)
    assert import_cash_flows(ledger, Account("moomoo", "2"), records) == (0, 1)
    flow = list_cash_flows(ledger)[0]
    assert flow.amount == Decimal("12.5")
    assert flow.flow_type == "Fund Redemption"
    assert list_events(ledger) == []


def test_moomoo_dividends_are_pending_declarations_not_cash_events(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    records = (
        {
            "pub_date": "2026/01/02",
            "statement": "Cash Dividend: 1.00000 USD Per Share",
            "process": "Proposed",
            "record_date": "2026/01/10",
            "ex_date": "2026/01/09",
            "dividend_payable_date": "2026/01/20",
        },
    )

    assert import_dividend_declarations(
        ledger,
        Account("moomoo", "2"),
        Instrument("SPY", "US", Currency.USD),
        records,
    ) == (1, 0)
    assert import_dividend_declarations(
        ledger,
        Account("moomoo", "2"),
        Instrument("SPY", "US", Currency.USD),
        records,
    ) == (0, 1)

    declaration = list_dividend_declarations(ledger)[0]
    assert declaration.amount_per_share == Decimal("1")
    assert declaration.currency is Currency.USD
    assert declaration.record_date == date(2026, 1, 10)
    assert list_events(ledger) == []


def test_moomoo_order_fee_records_preserve_components_and_raw_provenance(tmp_path, monkeypatch) -> None:
    from stonks_cli.ledger import list_fee_records

    ledger = encrypted_ledger(tmp_path, monkeypatch)
    order = {
        "order_id": "o-1",
        "currency": "USD",
        "create_time": "2026-01-02 09:30:00",
        "updated_time": "2026-01-02 09:31:00",
    }
    fee = {
        "order_id": "o-1",
        "fee_amount": "1.25",
        "fee_details": [("Commission", "1.00"), ("Tax Withholding", "0.25")],
    }

    assert import_order_fees(
        ledger, Account("moomoo", "2"), (fee,), (order,), opend_timezone="Asia/Singapore"
    ) == (2, 0)
    assert import_order_fees(
        ledger, Account("moomoo", "2"), (fee,), (order,), opend_timezone="Asia/Singapore"
    ) == (0, 2)

    records = list_fee_records(ledger)
    assert {(record.classification, record.amount) for record in records} == {
        ("Commission", Decimal("1.00")),
        ("Tax Withholding", Decimal("0.25")),
    }
    assert {record.transaction_id for record in records} == {"o-1"}
    assert {record.occurred_at for record in records} == {datetime(2026, 1, 2, 1, 31, tzinfo=UTC)}
    assert (ledger.sources / f"{records[0].raw_source_hash}.enc").is_file()


def test_moomoo_order_fee_records_reject_unreconciled_or_unlinked_rows(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    order = {"order_id": "o-1", "currency": "USD", "create_time": "2026-01-02 09:30:00"}

    with pytest.raises(ProviderError, match="do not reconcile"):
        import_order_fees(
            ledger,
            Account("moomoo", "2"),
            ({"order_id": "o-1", "fee_amount": "1", "fee_details": [("Commission", "0.5")]},),
            (order,),
            opend_timezone="Asia/Singapore",
        )
    with pytest.raises(ProviderError, match="no matching order"):
        import_order_fees(
            ledger,
            Account("moomoo", "2"),
            ({"order_id": "missing", "fee_amount": "1", "fee_details": [("Commission", "1")]},),
            (order,),
            opend_timezone="Asia/Singapore",
        )


def test_moomoo_stock_split_records_are_normalized_and_archived(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    instrument = Instrument("SPY", "US", Currency.USD)
    records = (
        {
            "reform_type": "Split",
            "rate": "1->5",
            "dir_deci_pub_date_str": "2026-01-02",
            "ex_date_str": "2026-01-03",
        },
        {"reform_type": "Reverse Split", "rate": "5->1", "dir_deci_pub_date_str": "2026-02-02"},
    )

    assert import_stock_splits(
        ledger, Account("moomoo", "2"), instrument, records, market_timezone="America/New_York"
    ) == (2, 0)
    assert import_stock_splits(
        ledger, Account("moomoo", "2"), instrument, records, market_timezone="America/New_York"
    ) == (0, 2)

    events = list_events(ledger)
    assert [event.quantity for event in events] == [Decimal("5"), Decimal("0.2")]
    assert events[0].occurred_at == datetime(2026, 1, 3, 5, tzinfo=UTC)
    assert events[0].metadata["effective_date_source"] == "ex_date_str"
    assert (ledger.sources / f"{events[0].metadata['raw_payload_hash']}.enc").is_file()


@pytest.mark.parametrize("rate", ("1->0", "1->", "invalid"))
def test_moomoo_stock_split_records_reject_invalid_rates(tmp_path, monkeypatch, rate: str) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)

    with pytest.raises(ProviderError, match="stock split"):
        import_stock_splits(
            ledger,
            Account("moomoo", "2"),
            Instrument("SPY", "US", Currency.USD),
            ({"reform_type": "Split", "rate": rate, "dir_deci_pub_date_str": "2026-01-02"},),
            market_timezone="America/New_York",
        )


def test_moomoo_import_rejects_unsupported_short_position(tmp_path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)

    try:
        import_account_snapshot(
            ledger,
            Account("moomoo", "2"),
            fills=(),
            positions=(
                {
                    "position_id": "p-1",
                    "code": "US.SPY",
                    "position_market": "US",
                    "currency": "USD",
                    "qty": "1",
                    "position_side": "SHORT",
                },
            ),
            balances=(),
            observed_at=datetime(2026, 1, 2, tzinfo=UTC),
            opend_timezone="Asia/Singapore",
        )
    except Exception as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("short positions must be rejected")


def test_moomoo_rate_limiter_waits_after_documented_account_cap() -> None:
    clock = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    limiter = MoomooRateLimiter(limit=2, window_seconds=30, clock=lambda: clock[0], sleeper=sleep)
    limiter.acquire("2")
    limiter.acquire("2")
    limiter.acquire("2")

    assert waits == [30]


def test_moomoo_limits_historical_candlestick_initial_pages_only() -> None:
    clock = [0.0]
    waits: list[float] = []
    contexts: list[QuoteContext] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    def quote_factory(_host: str, _port: int) -> QuoteContext:
        context = QuoteContext()
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(),
        lambda _host, _port: Context(),
        quote_factory,
        quote_rate_limiter=MoomooRateLimiter(
            limit=1, window_seconds=30, clock=lambda: clock[0], sleeper=sleep
        ),
    )

    provider.daily_prices(
        (Instrument("SPY", "US", Currency.USD), Instrument("QQQ", "US", Currency.USD)),
        date(2026, 1, 1),
        date(2026, 1, 2),
    )

    assert waits == [30]
    assert [len(context.calls) for context in contexts] == [2, 2]
    assert all(context.closed for context in contexts)
