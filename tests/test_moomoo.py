from __future__ import annotations

from datetime import date
from decimal import Decimal

from stonks_cli.moomoo import MoomooReadOnlyProvider, OpenDConnection
from stonks_cli.types import Currency, Instrument


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
