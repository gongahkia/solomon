from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from conftest import encrypted_ledger

from stonks_cli.ledger import (
    list_cash_flows,
    list_cash_snapshots,
    list_events,
    list_position_snapshots,
)
from stonks_cli.moomoo import (
    MoomooRateLimiter,
    MoomooReadOnlyProvider,
    OpenDConnection,
    import_account_snapshot,
    import_cash_flows,
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

    def close(self) -> None:
        self.closed = True


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


class SnapshotQuoteContext:
    def __init__(self) -> None:
        self.closed = False
        self.codes: list[list[str]] = []

    def get_market_snapshot(self, codes: list[str]):
        self.codes.append(codes)
        return 0, [
            {"code": code, "last_price": "100", "update_time": "2026-01-02 09:30:00"}
            for code in codes
        ]

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


def test_moomoo_rejects_non_loopback_endpoint() -> None:
    try:
        OpenDConnection("10.0.0.1", 11111)
    except Exception as error:
        assert "loopback" in str(error)
    else:
        raise AssertionError("non-loopback endpoint must be rejected")


def test_moomoo_reads_documented_account_data_only() -> None:
    provider = MoomooReadOnlyProvider(OpenDConnection(), lambda _host, _port: Context())

    assert provider.balances("2") == ({"cash": 100},)
    assert provider.cash_flows("2", "2026-07-22") == ({"cashflow_id": "1"},)
    assert provider.positions("2") == ({"code": "US.SPY"},)
    assert provider.historical_orders("2", "2026-01-01", "2026-01-02") == ({"order_id": "1"},)
    assert provider.historical_fills("2", "2026-01-01", "2026-01-02") == ({"deal_id": "1"},)


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
    provider = MoomooReadOnlyProvider(OpenDConnection(), lambda _host, _port: Context())
    monkeypatch.setattr(MoomooReadOnlyProvider, "from_installed_sdk", lambda _endpoint: provider)
    monkeypatch.setattr(MoomooReadOnlyProvider, "sdk_version", staticmethod(lambda: "10.9"))

    probe = MoomooReadOnlyProvider.probe(OpenDConnection())

    assert probe.sdk_version == "10.9"
    assert probe.account_count == 1


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


def test_moomoo_market_snapshots_are_explicitly_unknown_quality() -> None:
    contexts: list[SnapshotQuoteContext] = []

    def quote_factory(_host: str, _port: int) -> SnapshotQuoteContext:
        context = SnapshotQuoteContext()
        contexts.append(context)
        return context

    provider = MoomooReadOnlyProvider(
        OpenDConnection(), lambda _host, _port: Context(), quote_factory
    )
    snapshots = provider.market_snapshots(
        (Instrument("SPY", "US", Currency.USD),), datetime(2026, 1, 2, tzinfo=UTC)
    )

    assert snapshots[0].quality.value == "unknown"
    assert contexts[0].codes == [["US.SPY"]]
    assert contexts[0].closed is True


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
