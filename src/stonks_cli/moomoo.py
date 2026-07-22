from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module, metadata, util
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stonks_cli.errors import ProviderError
from stonks_cli.ledger import (
    import_fingerprint,
    ingest_events,
    store_cash_flow,
    store_cash_snapshot,
    store_dividend_declaration,
    store_fee_record,
    store_position_snapshot,
)
from stonks_cli.market_data import (
    DailyPrice,
    MarketSession,
    QuoteQuality,
    QuoteSnapshot,
    QuoteStatus,
    normalize_market_session,
)
from stonks_cli.plugins import Capability, PluginManifest, register_builtin_provider
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    Account,
    BrokerCashFlow,
    BrokerCashSnapshot,
    BrokerDividendDeclaration,
    BrokerFeeRecord,
    BrokerPositionSnapshot,
    Currency,
    EventKind,
    Instrument,
    LedgerEvent,
    SourceProvenance,
)

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_READ_METHODS = frozenset(
    {
        "get_acc_list",
        "accinfo_query",
        "get_acc_cash_flow",
        "position_list_query",
        "history_order_list_query",
        "history_deal_list_query",
        "order_fee_query",
    }
)
_MARKET_CURRENCIES = {"HK": Currency.HKD, "SH": Currency.CNY, "SZ": Currency.CNY, "SG": Currency.SGD, "US": Currency.USD}
_CASH_FIELDS = (("hk_cash", Currency.HKD), ("us_cash", Currency.USD), ("cn_cash", Currency.CNY), ("sg_cash", Currency.SGD))
_SDK_VERSION = re.compile(r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)(?:\.[0-9]+)?\Z")
_MAX_HISTORICAL_PAGES = 100
_MAX_HISTORICAL_ROWS = 100_000
_MAX_CORPORATE_ACTION_PAGES = 100
_MAX_CORPORATE_ACTION_ROWS = 5_000
_MAX_QUOTE_AGE = timedelta(minutes=5)
_QUOTE_TIMEZONES = {"US": "America/New_York", "SG": "Asia/Singapore"}
_ENTITLED_QUOTE_STATUSES = frozenset({"available", "entitled", "real_time", "realtime"})
_DELAYED_QUOTE_STATUSES = frozenset({"delayed", "delay"})
_UNAVAILABLE_QUOTE_STATUSES = frozenset({"unavailable", "unavailable_data"})
_UNENTITLED_QUOTE_STATUSES = frozenset({"unentitled", "not_entitled", "no_permission"})
_DIVIDEND_AMOUNT = re.compile(
    r"\bcash dividend\s*:\s*(?P<amount>[0-9]+(?:\.[0-9]+)?)\s+(?P<currency>CNY|HKD|SGD|USD)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OpenDConnection:
    host: str = "127.0.0.1"
    port: int = 11111

    def __post_init__(self) -> None:
        if (
            not isinstance(self.host, str)
            or self.host.lower() not in _LOCAL_HOSTS
            or isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ProviderError("Moomoo OpenD must be a valid loopback endpoint")


@dataclass(frozen=True)
class MoomooAccount:
    account_id: str
    account_index: int
    environment: str


@dataclass(frozen=True)
class OpenDProbe:
    endpoint: OpenDConnection
    sdk_version: str | None
    account_count: int


@dataclass(frozen=True)
class OpenDSDKStatus:
    available: bool
    version: str | None
    reason: str | None


@dataclass(frozen=True)
class MoomooSyncResult:
    fills_inserted: int
    fills_skipped: int
    position_snapshots: int
    cash_snapshots: int
    source_hashes: tuple[str, ...]


class MoomooRateLimiter:
    """Conservative process-local sliding-window limiter."""

    def __init__(
        self,
        *,
        limit: int = 10,
        window_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("Moomoo rate limiter requires a positive limit and window")
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._requests: dict[str, list[float]] = {}

    def acquire(self, account_id: str) -> None:
        now = self.clock()
        requests = self._requests.setdefault(account_id, [])
        requests[:] = [at for at in requests if now - at < self.window_seconds]
        if len(requests) >= self.limit:
            self.sleeper(max(0, self.window_seconds - (now - requests[0])))
            now = self.clock()
            requests[:] = [at for at in requests if now - at < self.window_seconds]
        requests.append(now)


class MoomooReadOnlyProvider:
    manifest = PluginManifest(
        "moomoo",
        "1.0.0",
        frozenset(
            {
                Capability.ACCOUNTS,
                Capability.BALANCES,
                Capability.POSITIONS,
                Capability.TRANSACTIONS,
                Capability.MARKET_DATA,
            }
        ),
    )

    def __init__(
        self,
        endpoint: OpenDConnection,
        context_factory: Callable[[str, int], Any],
        quote_context_factory: Callable[[str, int], Any] | None = None,
        rate_limiter: MoomooRateLimiter | None = None,
        quote_rate_limiter: MoomooRateLimiter | None = None,
        corporate_action_rate_limiter: MoomooRateLimiter | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.context_factory = context_factory
        self.quote_context_factory = quote_context_factory
        self.rate_limiter = rate_limiter or MoomooRateLimiter()
        self.quote_rate_limiter = quote_rate_limiter or MoomooRateLimiter(limit=60)
        self.corporate_action_rate_limiter = corporate_action_rate_limiter or MoomooRateLimiter(limit=30)

    @classmethod
    def from_installed_sdk(cls, endpoint: OpenDConnection) -> MoomooReadOnlyProvider:
        status = cls.sdk_status()
        if not status.available:
            raise ProviderError(f"Moomoo SDK unavailable:{status.reason}")
        try:
            module: Any = import_module("moomoo")
            context_class = module.OpenSecTradeContext
            quote_context_class = module.OpenQuoteContext
        except (AttributeError, ImportError) as error:
            raise ProviderError("Moomoo SDK unavailable:module_import") from error

        def factory(host: str, port: int) -> Any:
            return context_class(host=host, port=port)

        def quote_factory(host: str, port: int) -> Any:
            return quote_context_class(host=host, port=port)

        return cls(endpoint, factory, quote_factory)

    @staticmethod
    def sdk_status() -> OpenDSDKStatus:
        try:
            version = metadata.version("moomoo-api").strip()
        except metadata.PackageNotFoundError:
            return OpenDSDKStatus(False, None, "distribution_missing")
        try:
            module = util.find_spec("moomoo")
        except (AttributeError, ImportError, ValueError):
            return OpenDSDKStatus(False, version, "module_malformed")
        if module is None:
            return OpenDSDKStatus(False, version, "module_missing")
        match = _SDK_VERSION.fullmatch(version)
        if match is None:
            return OpenDSDKStatus(False, version, "version_malformed")
        if int(match["major"]) != 10 or int(match["minor"]) < 9:
            return OpenDSDKStatus(False, version, "version_incompatible")
        return OpenDSDKStatus(True, version, None)

    @classmethod
    def sdk_version(cls) -> str | None:
        return cls.sdk_status().version

    def accounts(self) -> tuple[MoomooAccount, ...]:
        records = self._call("get_acc_list")
        parsed: list[MoomooAccount] = []
        for row in _records(records):
            try:
                raw_account_id = row["acc_id"]
                raw_index = row["acc_index"]
                raw_environment = row["trd_env"]
                if raw_account_id is None or raw_environment is None or isinstance(raw_index, bool):
                    raise ValueError
                account_id = str(raw_account_id).strip()
                account_index = int(raw_index)
                environment = str(raw_environment).strip().upper()
                if not account_id or account_index < 0 or not environment:
                    raise ValueError
                parsed.append(MoomooAccount(account_id, account_index, environment))
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderError("malformed Moomoo account record") from error
        if len({item.account_id for item in parsed}) != len(parsed):
            raise ProviderError("duplicate Moomoo account IDs")
        return tuple(sorted(parsed, key=lambda item: (item.account_index, item.account_id)))

    def selected_account(self, account_id: str) -> MoomooAccount:
        if not isinstance(account_id, str) or not (selected_id := account_id.strip()):
            raise ProviderError("Moomoo account selection is required")
        for account in self.accounts():
            if account.account_id == selected_id:
                return account
        raise ProviderError("Moomoo account selection is unavailable")

    @classmethod
    def probe(cls, endpoint: OpenDConnection) -> OpenDProbe:
        status = cls.sdk_status()
        if not status.available:
            raise ProviderError(f"Moomoo SDK unavailable:{status.reason}")
        provider = cls.from_installed_sdk(endpoint)
        return OpenDProbe(endpoint, status.version, len(provider.accounts()))

    def positions(self, account_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(_records(self._call("position_list_query", acc_id=account_id)))

    def balances(self, account_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(_records(self._call("accinfo_query", acc_id=account_id)))

    def cash_flows(self, account_id: str, clearing_date: str) -> tuple[dict[str, Any], ...]:
        if not clearing_date:
            raise ProviderError("Moomoo cash flow clearing date is required")
        return tuple(
            _records(
                self._call("get_acc_cash_flow", acc_id=account_id, clearing_date=clearing_date)
            )
        )

    def historical_orders(
        self, account_id: str, start: str, end: str
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            _records(
                self._call("history_order_list_query", acc_id=account_id, start=start, end=end)
            )
        )

    def historical_fills(self, account_id: str, start: str, end: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            _records(self._call("history_deal_list_query", acc_id=account_id, start=start, end=end))
        )

    def order_fees(
        self, account_id: str, order_ids: Sequence[str]
    ) -> tuple[dict[str, Any], ...]:
        selected = self.selected_account(account_id)
        identifiers = tuple(_nonempty_strings(order_ids, "Moomoo order IDs"))
        if not identifiers:
            return ()
        return tuple(
            _records(
                self._call(
                    "order_fee_query", identifiers, rate_limit_account_id=selected.account_id
                )
            )
        )

    def transaction_records(
        self, account: Account, start: datetime, end: datetime
    ) -> tuple[dict[str, Any], ...]:
        if account.provider_id != self.manifest.identifier:
            raise ProviderError("Moomoo account provider is invalid")
        if start.tzinfo is None or end.tzinfo is None or start > end:
            raise ProviderError("Moomoo transaction range is invalid")
        return self.historical_fills(
            account.account_id,
            start.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            end.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        )

    def daily_prices(
        self, instruments: tuple[Instrument, ...], start: date, end: date
    ) -> tuple[DailyPrice, ...]:
        if start > end:
            raise ProviderError("Moomoo market-data date range is invalid")
        if self.quote_context_factory is None:
            raise ProviderError("Moomoo quote context is unavailable")
        prices: list[DailyPrice] = []
        for instrument in instruments:
            rows = self._historical_bars(instrument, start, end)
            source_hash = hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            seen_dates: set[date] = set()
            for row in rows:
                try:
                    session_date = date.fromisoformat(str(row["time_key"]).split()[0])
                    if session_date < start or session_date > end or session_date in seen_dates:
                        raise ValueError("Moomoo daily bar session date is invalid")
                    price = DailyPrice(
                        instrument,
                        session_date,
                        _positive_decimal(row["close"], "Moomoo daily close"),
                        source_hash,
                        _positive_decimal(row["open"], "Moomoo daily open"),
                        _positive_decimal(row["high"], "Moomoo daily high"),
                        _positive_decimal(row["low"], "Moomoo daily low"),
                    )
                except (KeyError, ValueError) as error:
                    raise ProviderError("malformed Moomoo daily bar") from error
                seen_dates.add(session_date)
                prices.append(price)
        return tuple(sorted(prices, key=lambda item: (item.instrument.key, item.session_date)))

    def market_snapshots(
        self,
        instruments: tuple[Instrument, ...],
        observed_at: datetime,
        *,
        maximum_age: timedelta = _MAX_QUOTE_AGE,
        maximum_spread_bps: Decimal = Decimal("100"),
    ) -> tuple[QuoteSnapshot, ...]:
        if not instruments:
            return ()
        if maximum_age < timedelta(0) or maximum_spread_bps < 0:
            raise ProviderError("Moomoo quote limits must be non-negative")
        if self.quote_context_factory is None:
            return _unavailable_snapshots(instruments, observed_at, "quote_context_unavailable")
        observed_at = _utc_timestamp(observed_at)
        requested = {f"{item.market}.{item.symbol}": item for item in instruments}
        if len(requested) != len(instruments):
            raise ProviderError("Moomoo snapshot instruments are duplicated")
        rows: list[dict[str, Any]] = []
        market_state: dict[str, Any] = {}
        failure: str | None = None
        context: Any | None = None
        try:
            context = self.quote_context_factory(self.endpoint.host, self.endpoint.port)
            call = getattr(context, "get_market_snapshot", None)
            if not callable(call):
                failure = "get_market_snapshot_unavailable"
            else:
                for index in range(0, len(instruments), 400):
                    codes = [f"{item.market}.{item.symbol}" for item in instruments[index : index + 400]]
                    self.quote_rate_limiter.acquire("get_market_snapshot")
                    response = call(codes)
                    if not isinstance(response, tuple) or len(response) != 2 or response[0] != 0:
                        failure = "get_market_snapshot_failed"
                        break
                    rows.extend(_records(response[1]))
                if failure is None:
                    market_state = _quote_market_state(context)
        except Exception as error:
            failure = f"get_market_snapshot_error:{type(error).__name__}"
        finally:
            if context is not None:
                close = getattr(context, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        failure = "quote_context_close_failed"
                else:
                    failure = "quote_context_close_unavailable"
        if failure is not None:
            return _unavailable_snapshots(instruments, observed_at, failure)
        snapshots_by_code: dict[str, QuoteSnapshot] = {}
        for row in rows:
            try:
                code = str(row["code"]).strip().upper()
                instrument = requested[code]
            except (KeyError, ValueError):
                continue
            if code in snapshots_by_code:
                snapshots_by_code[code] = _malformed_snapshot(
                    instrument, observed_at, row, "duplicate_snapshot"
                )
                continue
            snapshots_by_code[code] = _normalize_quote_snapshot(
                instrument,
                row,
                observed_at,
                market_state,
                maximum_age,
                maximum_spread_bps,
            )
        for code, instrument in requested.items():
            snapshots_by_code.setdefault(
                code, _unavailable_snapshot(instrument, observed_at, "snapshot_omitted")
            )
        return tuple(sorted(snapshots_by_code.values(), key=lambda item: item.instrument.key))

    def corporate_splits(self, instrument: Instrument) -> tuple[dict[str, Any], ...]:
        if self.quote_context_factory is None:
            raise ProviderError("Moomoo quote context is unavailable")
        context = self.quote_context_factory(self.endpoint.host, self.endpoint.port)
        rows: list[dict[str, Any]] = []
        next_key: str | None = None
        seen_keys: set[str] = set()
        try:
            for _ in range(_MAX_CORPORATE_ACTION_PAGES):
                self.corporate_action_rate_limiter.acquire("get_corporate_actions_stock_splits")
                call = getattr(context, "get_corporate_actions_stock_splits", None)
                if not callable(call):
                    raise ProviderError("Moomoo quote context does not support:get_corporate_actions_stock_splits")
                response = call(f"{instrument.market}.{instrument.symbol}", next_key=next_key, num=50)
                if not isinstance(response, tuple) or len(response) != 2 or response[0] != 0:
                    raise ProviderError("Moomoo read failed:get_corporate_actions_stock_splits")
                payload = response[1]
                if not isinstance(payload, dict):
                    raise ProviderError("Moomoo stock split response is malformed")
                page_rows = payload.get("split_list")
                if not isinstance(page_rows, Sequence) or isinstance(page_rows, (str, bytes)):
                    raise ProviderError("Moomoo stock split response is malformed")
                if not all(isinstance(row, dict) for row in page_rows):
                    raise ProviderError("Moomoo stock split response is malformed")
                rows.extend(page_rows)
                if len(rows) > _MAX_CORPORATE_ACTION_ROWS:
                    raise ProviderError("Moomoo stock split pagination exceeded row limit")
                next_key = _corporate_action_next_key(payload.get("next_key"))
                if next_key is None:
                    return tuple(rows)
                if next_key in seen_keys:
                    raise ProviderError("Moomoo stock split pagination repeated page key")
                seen_keys.add(next_key)
            raise ProviderError("Moomoo stock split pagination exceeded page limit")
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("Moomoo read failed:get_corporate_actions_stock_splits") from error
        finally:
            close = getattr(context, "close", None)
            if not callable(close):
                raise ProviderError("Moomoo quote context cannot be closed")
            close()

    def corporate_dividends(self, instrument: Instrument) -> tuple[dict[str, Any], ...]:
        if self.quote_context_factory is None:
            raise ProviderError("Moomoo quote context is unavailable")
        context = self.quote_context_factory(self.endpoint.host, self.endpoint.port)
        try:
            self.corporate_action_rate_limiter.acquire("get_corporate_actions_dividends")
            call = getattr(context, "get_corporate_actions_dividends", None)
            if not callable(call):
                raise ProviderError("Moomoo quote context does not support:get_corporate_actions_dividends")
            response = call(f"{instrument.market}.{instrument.symbol}")
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != 0:
                raise ProviderError("Moomoo read failed:get_corporate_actions_dividends")
            payload = response[1]
            if not isinstance(payload, dict):
                raise ProviderError("Moomoo dividend response is malformed")
            rows = payload.get("dividend_list")
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise ProviderError("Moomoo dividend response is malformed")
            if not all(isinstance(row, dict) for row in rows):
                raise ProviderError("Moomoo dividend response is malformed")
            return tuple(rows)
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("Moomoo read failed:get_corporate_actions_dividends") from error
        finally:
            close = getattr(context, "close", None)
            if not callable(close):
                raise ProviderError("Moomoo quote context cannot be closed")
            close()

    def _historical_bars(
        self, instrument: Instrument, start: date, end: date
    ) -> list[dict[str, Any]]:
        if self.quote_context_factory is None:
            raise ProviderError("Moomoo quote context is unavailable")
        self.quote_rate_limiter.acquire("request_history_kline")
        context = self.quote_context_factory(self.endpoint.host, self.endpoint.port)
        rows: list[dict[str, Any]] = []
        page_key: str | bytes | None = None
        seen_page_keys: set[str | bytes] = set()
        try:
            for _ in range(_MAX_HISTORICAL_PAGES):
                call = getattr(context, "request_history_kline", None)
                if not callable(call):
                    raise ProviderError("Moomoo quote context does not support:request_history_kline")
                response = call(
                    f"{instrument.market}.{instrument.symbol}",
                    start=start.isoformat(),
                    end=end.isoformat(),
                    max_count=1000,
                    page_req_key=page_key,
                )
                if not isinstance(response, tuple) or len(response) != 3 or response[0] != 0:
                    raise ProviderError("Moomoo read failed:request_history_kline")
                page_rows = list(_records(response[1]))
                rows.extend(page_rows)
                if len(rows) > _MAX_HISTORICAL_ROWS:
                    raise ProviderError("Moomoo historical pagination exceeded row limit")
                page_key = _pagination_key(response[2])
                if page_key is None:
                    return rows
                if page_key in seen_page_keys:
                    raise ProviderError("Moomoo historical pagination repeated page key")
                seen_page_keys.add(page_key)
            raise ProviderError("Moomoo historical pagination exceeded page limit")
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("Moomoo read failed:request_history_kline") from error
        finally:
            close = getattr(context, "close", None)
            if not callable(close):
                raise ProviderError("Moomoo quote context cannot be closed")
            close()

    def _call(
        self, method: str, *args: Any, rate_limit_account_id: str | None = None, **kwargs: Any
    ) -> Any:
        if method not in _READ_METHODS:
            raise ProviderError(f"Moomoo method is not read-only:{method}")
        account_id = rate_limit_account_id or kwargs.get("acc_id")
        if isinstance(account_id, str) and account_id:
            self.rate_limiter.acquire(account_id)
        context = self.context_factory(self.endpoint.host, self.endpoint.port)
        try:
            call = getattr(context, method, None)
            if not callable(call):
                raise ProviderError(f"Moomoo context does not support:{method}")
            response = call(*args, **kwargs)
            if not isinstance(response, tuple) or len(response) != 2 or response[0] != 0:
                raise ProviderError(f"Moomoo read failed:{method}")
            return response[1]
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(f"Moomoo read failed:{method}") from error
        finally:
            close = getattr(context, "close", None)
            if not callable(close):
                raise ProviderError("Moomoo context cannot be closed")
            close()


register_builtin_provider(MoomooReadOnlyProvider)


def _records(value: Any) -> Sequence[dict[str, Any]]:
    converter = getattr(value, "to_dict", None)
    records = converter("records") if callable(converter) else value
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ProviderError("Moomoo response is not a record sequence")
    if not all(isinstance(record, dict) for record in records):
        raise ProviderError("Moomoo response contains malformed records")
    return records


def _pagination_key(value: Any) -> str | bytes | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) and value:
        return value
    raise ProviderError("Moomoo historical pagination token is invalid")


def _corporate_action_next_key(value: Any) -> str | None:
    if value == "-1":
        return None
    if isinstance(value, str) and value:
        return value
    raise ProviderError("Moomoo stock split pagination token is invalid")


def import_account_snapshot(
    ledger: EncryptedLedger,
    account: Account,
    *,
    fills: Sequence[dict[str, Any]],
    positions: Sequence[dict[str, Any]],
    balances: Sequence[dict[str, Any]],
    observed_at: datetime,
    opend_timezone: str,
) -> MoomooSyncResult:
    """Archive Moomoo payloads and import only completed fills plus observed snapshots."""
    if account.provider_id != "moomoo":
        raise ProviderError("Moomoo import requires a Moomoo account")
    observed_at = _utc_timestamp(observed_at)
    source_hashes = (
        _archive_response(ledger, account, "fills", fills),
        _archive_response(ledger, account, "positions", positions),
        _archive_response(ledger, account, "balances", balances),
    )
    events = tuple(
        _fill_to_event(ledger, account, row, opend_timezone)
        for row in sorted(fills, key=lambda item: str(item.get("deal_id", "")))
    )
    inserted, skipped = ingest_events(ledger, events)
    position_count = sum(
        store_position_snapshot(
            ledger, _position_to_snapshot(ledger, account, row, observed_at)
        )
        for row in positions
    )
    cash_count = sum(
        store_cash_snapshot(ledger, snapshot)
        for row in balances
        for snapshot in _balance_to_snapshots(ledger, account, row, observed_at)
    )
    return MoomooSyncResult(inserted, skipped, position_count, cash_count, source_hashes)


def import_cash_flows(
    ledger: EncryptedLedger, account: Account, records: Sequence[dict[str, Any]]
) -> tuple[int, int]:
    """Store documented cash flows without guessing their accounting classification."""
    if account.provider_id != "moomoo":
        raise ProviderError("Moomoo import requires a Moomoo account")
    inserted = skipped = 0
    for row in records:
        try:
            flow_id = _identifier(row, "cashflow_id")
            source, _ = _record_source(ledger, account, "cash_flow", flow_id, row)
            flow = BrokerCashFlow(
                source,
                account,
                date.fromisoformat(str(row["clearing_date"])),
                date.fromisoformat(str(row["settlement_date"])),
                Currency(str(row["currency"]).strip().upper()),
                str(row["cashflow_type"]),
                str(row["cashflow_direction"]),
                Decimal(str(row["cashflow_amount"])),
                None if row.get("cashflow_remark") is None else str(row["cashflow_remark"]),
            )
        except (KeyError, ValueError) as error:
            raise ProviderError("malformed Moomoo cash flow record") from error
        if store_cash_flow(ledger, flow):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def import_dividend_declarations(
    ledger: EncryptedLedger,
    account: Account,
    instrument: Instrument,
    records: Sequence[dict[str, Any]],
) -> tuple[int, int]:
    """Store announced dividends as pending evidence without cash events."""
    if account.provider_id != "moomoo":
        raise ProviderError("Moomoo import requires a Moomoo account")
    inserted = skipped = 0
    for row in records:
        try:
            raw_payload = {"instrument": instrument.key, "dividend": row}
            identifier = hashlib.sha256(_canonical_json(raw_payload)).hexdigest()
            source, raw_hash = _record_source(
                ledger, account, "dividend_declaration", identifier, raw_payload
            )
            amount_per_share, currency = _dividend_amount_per_share(row.get("statement"))
            declaration = BrokerDividendDeclaration(
                source=source,
                raw_source_hash=raw_hash,
                account=account,
                instrument=instrument,
                announced_at=_moomoo_date(row.get("pub_date")),
                status=_optional_text(row.get("process")),
                record_date=_moomoo_date(row.get("record_date")),
                ex_date=_moomoo_date(row.get("ex_date")),
                payable_date=_moomoo_date(row.get("dividend_payable_date")),
                statement=_optional_text(row.get("statement")),
                amount_per_share=amount_per_share,
                currency=currency,
            )
        except ValueError as error:
            raise ProviderError("malformed Moomoo dividend record") from error
        if store_dividend_declaration(ledger, declaration):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def import_order_fees(
    ledger: EncryptedLedger,
    account: Account,
    fee_records: Sequence[dict[str, Any]],
    orders: Sequence[dict[str, Any]],
    *,
    opend_timezone: str,
) -> tuple[int, int]:
    """Store observed fee components without tax inference or netting."""
    if account.provider_id != "moomoo":
        raise ProviderError("Moomoo import requires a Moomoo account")
    orders_by_id: dict[str, dict[str, Any]] = {}
    for order in orders:
        try:
            order_id = _identifier(order, "order_id")
        except (KeyError, ValueError) as error:
            raise ProviderError("malformed Moomoo order record") from error
        if order_id in orders_by_id:
            raise ProviderError("duplicate Moomoo order record")
        orders_by_id[order_id] = order
    inserted = skipped = 0
    for fee_record in fee_records:
        try:
            order_id = _identifier(fee_record, "order_id")
            order = orders_by_id[order_id]
        except (KeyError, ValueError) as error:
            raise ProviderError("Moomoo fee record has no matching order") from error
        for fee in _fee_records_from_moomoo_row(
            ledger, account, fee_record, order, opend_timezone
        ):
            if store_fee_record(ledger, fee):
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


def import_stock_splits(
    ledger: EncryptedLedger,
    account: Account,
    instrument: Instrument,
    records: Sequence[dict[str, Any]],
    *,
    market_timezone: str,
) -> tuple[int, int]:
    """Normalize documented stock split and reverse split records into ledger events."""
    if account.provider_id != "moomoo":
        raise ProviderError("Moomoo import requires a Moomoo account")
    events = tuple(
        _split_to_event(ledger, account, instrument, row, market_timezone) for row in records
    )
    return ingest_events(ledger, events)


def _fill_to_event(
    ledger: EncryptedLedger, account: Account, row: dict[str, Any], opend_timezone: str
) -> LedgerEvent:
    try:
        deal_id = _identifier(row, "deal_id")
        side = str(row["trd_side"]).strip().upper()
        kind = {"BUY": EventKind.BUY, "SELL": EventKind.SELL}[side]
        instrument = _instrument_from_moomoo_row(row, "deal_market")
        quantity = _positive_decimal(row["qty"], "Moomoo fill quantity")
        price = _positive_decimal(row["price"], "Moomoo fill price")
        occurred_at = _opend_timestamp(row["create_time"], opend_timezone)
    except (KeyError, ValueError, ZoneInfoNotFoundError) as error:
        raise ProviderError("malformed Moomoo fill record") from error
    source, raw_hash = _record_source(ledger, account, "fill", deal_id, row)
    canonical = {
        "deal_id": deal_id,
        "order_id": str(row.get("order_id", "")),
        "trd_side": side,
        "code": row.get("code"),
        "qty": str(quantity),
        "price": str(price),
        "create_time": str(row.get("create_time")),
    }
    return LedgerEvent(
        fingerprint=import_fingerprint(source, canonical),
        source=source,
        account=account,
        occurred_at=occurred_at,
        kind=kind,
        currency=instrument.currency,
        amount=quantity * price,
        quantity=quantity,
        instrument=instrument,
        metadata={
            "order_id": str(row.get("order_id", "")),
            "raw_payload_hash": raw_hash,
            "vendor": "moomoo",
        },
    )


def _fee_records_from_moomoo_row(
    ledger: EncryptedLedger,
    account: Account,
    fee_record: dict[str, Any],
    order: dict[str, Any],
    opend_timezone: str,
) -> tuple[BrokerFeeRecord, ...]:
    try:
        order_id = _identifier(fee_record, "order_id")
        currency = Currency(str(order["currency"]).strip().upper())
        timestamp = _opend_timestamp(order.get("updated_time") or order["create_time"], opend_timezone)
        total = _nonnegative_decimal(fee_record["fee_amount"], "Moomoo fee amount")
        details = fee_record["fee_details"]
        if not isinstance(details, Sequence) or isinstance(details, (str, bytes)):
            raise ValueError("Moomoo fee details must be a sequence")
    except (KeyError, ValueError, ZoneInfoNotFoundError) as error:
        raise ProviderError("malformed Moomoo fee record") from error
    parsed: list[tuple[str, Decimal]] = []
    for detail in details:
        if (
            not isinstance(detail, Sequence)
            or isinstance(detail, (str, bytes))
            or len(detail) != 2
        ):
            raise ProviderError("malformed Moomoo fee detail")
        classification = str(detail[0]).strip()
        if not classification:
            raise ProviderError("malformed Moomoo fee detail")
        try:
            amount = _nonnegative_decimal(detail[1], "Moomoo fee detail amount")
        except ValueError as error:
            raise ProviderError("malformed Moomoo fee detail") from error
        parsed.append((classification, amount))
    if not parsed or sum(amount for _, amount in parsed) != total:
        raise ProviderError("Moomoo fee details do not reconcile to total")
    records: list[BrokerFeeRecord] = []
    raw_payload = {"fee": fee_record, "order": order}
    for index, (classification, amount) in enumerate(parsed):
        source, raw_hash = _record_source(
            ledger, account, "fee", f"{order_id}:{index}", raw_payload
        )
        records.append(
            BrokerFeeRecord(
                source,
                raw_hash,
                account,
                currency,
                amount,
                classification,
                order_id,
                timestamp,
            )
        )
    return tuple(records)


def _split_to_event(
    ledger: EncryptedLedger,
    account: Account,
    instrument: Instrument,
    row: dict[str, Any],
    market_timezone: str,
) -> LedgerEvent:
    try:
        reform_type = str(row["reform_type"]).strip()
        if not reform_type:
            raise ValueError("Moomoo split reorganization type is required")
        rate = str(row["rate"]).strip()
        ratio = _split_ratio(rate)
        effective_date_source = "ex_date_str" if row.get("ex_date_str") else "dir_deci_pub_date_str"
        effective_date = date.fromisoformat(str(row[effective_date_source]).strip())
        timezone = ZoneInfo(market_timezone)
    except (KeyError, ValueError, ZoneInfoNotFoundError) as error:
        raise ProviderError("malformed Moomoo stock split record") from error
    occurred_at = datetime.combine(effective_date, datetime.min.time(), tzinfo=timezone).astimezone(UTC)
    raw_payload = {"instrument": instrument.key, "split": row}
    identity = hashlib.sha256(_canonical_json(raw_payload)).hexdigest()
    source, raw_hash = _record_source(ledger, account, "split", identity, raw_payload)
    canonical = {
        "instrument": instrument.key,
        "reform_type": reform_type,
        "rate": rate,
        "effective_date": effective_date.isoformat(),
    }
    return LedgerEvent(
        fingerprint=import_fingerprint(source, canonical),
        source=source,
        account=account,
        occurred_at=occurred_at,
        kind=EventKind.SPLIT,
        currency=instrument.currency,
        amount=Decimal("0"),
        quantity=ratio,
        instrument=instrument,
        metadata={
            "effective_date_source": effective_date_source,
            "raw_payload_hash": raw_hash,
            "reform_type": reform_type,
            "vendor": "moomoo",
        },
    )


def _position_to_snapshot(
    ledger: EncryptedLedger, account: Account, row: dict[str, Any], observed_at: datetime
) -> BrokerPositionSnapshot:
    try:
        if str(row.get("position_side", "LONG")).strip().upper() != "LONG":
            raise ValueError("short position")
        position_id = _identifier(row, "position_id")
        instrument = _instrument_from_moomoo_row(row, "position_market")
        quantity = _nonnegative_decimal(row["qty"], "Moomoo position quantity")
    except (KeyError, ValueError) as error:
        raise ProviderError("malformed or unsupported Moomoo position record") from error
    source, _ = _record_source(
        ledger, account, "position", f"{position_id}:{observed_at.isoformat()}", row
    )
    return BrokerPositionSnapshot(source, account, instrument, quantity, observed_at)


def _balance_to_snapshots(
    ledger: EncryptedLedger, account: Account, row: dict[str, Any], observed_at: datetime
) -> tuple[BrokerCashSnapshot, ...]:
    values: dict[Currency, Decimal] = {}
    for field, currency in _CASH_FIELDS:
        value = row.get(field)
        if value not in (None, "", "N/A"):
            values[currency] = _nonnegative_decimal(value, f"Moomoo {field}")
    if not values and row.get("cash") not in (None, "", "N/A"):
        try:
            currency = Currency(str(row["currency"]).strip().upper())
        except (KeyError, ValueError) as error:
            raise ProviderError("Moomoo single-currency cash response has no supported currency") from error
        values[currency] = _nonnegative_decimal(row["cash"], "Moomoo cash")
    snapshots: list[BrokerCashSnapshot] = []
    for currency, amount in sorted(values.items(), key=lambda item: item[0].value):
        source, _ = _record_source(
            ledger,
            account,
            "cash",
            f"{currency.value}:{observed_at.isoformat()}",
            row,
        )
        snapshots.append(BrokerCashSnapshot(source, account, currency, amount, observed_at))
    return tuple(snapshots)


def _record_source(
    ledger: EncryptedLedger,
    account: Account,
    record_type: str,
    record_id: str,
    raw_record: dict[str, Any],
) -> tuple[SourceProvenance, str]:
    raw_hash = ledger.archive_source(_canonical_json(raw_record))
    identity = {
        "account_id": account.account_id,
        "provider": "moomoo",
        "record_id": record_id,
        "record_type": record_type,
    }
    identity_hash = ledger.archive_source(_canonical_json(identity))
    return SourceProvenance("moomoo", identity_hash, f"{record_type}:{record_id}"), raw_hash


def _archive_response(
    ledger: EncryptedLedger,
    account: Account,
    response_type: str,
    records: Sequence[dict[str, Any]],
) -> str:
    return ledger.archive_source(
        _canonical_json(
            {
                "account_id": account.account_id,
                "provider": "moomoo",
                "response_type": response_type,
                "records": records,
            }
        )
    )


def _instrument_from_moomoo_row(row: dict[str, Any], market_field: str) -> Instrument:
    code = str(row["code"]).strip().upper()
    market, separator, symbol = code.partition(".")
    if not separator or not market or not symbol:
        raise ValueError("Moomoo code must be MARKET.SYMBOL")
    row_market = str(row.get(market_field, market)).strip().upper()
    if row_market and row_market != market:
        raise ValueError("Moomoo code market does not match record market")
    try:
        currency = Currency(str(row.get("currency", "")).strip().upper())
    except ValueError:
        try:
            currency = _MARKET_CURRENCIES[market]
        except KeyError as error:
            raise ValueError("Moomoo market has no configured currency") from error
    name = str(row.get("stock_name", "")).strip() or None
    return Instrument(symbol, market, currency, name)


def _quote_market_state(context: Any) -> dict[str, Any]:
    call = getattr(context, "get_global_state", None)
    if not callable(call):
        return {}
    try:
        response = call()
    except Exception:
        return {}
    if (
        not isinstance(response, tuple)
        or len(response) != 2
        or response[0] != 0
        or not isinstance(response[1], dict)
    ):
        return {}
    return response[1]


def _quote_fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _unavailable_snapshots(
    instruments: tuple[Instrument, ...], observed_at: datetime, reason: str
) -> tuple[QuoteSnapshot, ...]:
    return tuple(
        _unavailable_snapshot(instrument, observed_at, reason)
        for instrument in sorted(instruments, key=lambda item: item.key)
    )


def _unavailable_snapshot(
    instrument: Instrument, observed_at: datetime, reason: str
) -> QuoteSnapshot:
    raw_payload: dict[str, object] = {
        "code": f"{instrument.market}.{instrument.symbol}",
        "error": reason,
        "subscription_mode": "none",
    }
    fingerprint = _quote_fingerprint(raw_payload)
    return QuoteSnapshot(
        instrument,
        None,
        observed_at,
        QuoteQuality.UNKNOWN,
        fingerprint,
        status=QuoteStatus.UNAVAILABLE,
        order_book_status="unavailable",
        market_session=MarketSession.UNKNOWN,
        subscription_mode="none",
        provider_fingerprint=fingerprint,
        raw_payload=raw_payload,
    )


def _malformed_snapshot(
    instrument: Instrument, observed_at: datetime, row: dict[str, Any], reason: str
) -> QuoteSnapshot:
    raw_payload: dict[str, object] = {
        "snapshot": row,
        "error": reason,
        "subscription_mode": "none",
    }
    fingerprint = _quote_fingerprint(raw_payload)
    return QuoteSnapshot(
        instrument,
        None,
        observed_at,
        QuoteQuality.UNKNOWN,
        fingerprint,
        status=QuoteStatus.MALFORMED,
        order_book_status="malformed",
        market_session=MarketSession.UNKNOWN,
        subscription_mode="none",
        provider_fingerprint=fingerprint,
        raw_payload=raw_payload,
    )


def _quote_status(row: dict[str, Any]) -> tuple[QuoteStatus, QuoteQuality]:
    value = _optional_text(row.get("quote_status") or row.get("data_status"))
    normalized = value.lower().replace("-", "_").replace(" ", "_") if value else ""
    if normalized in _ENTITLED_QUOTE_STATUSES:
        return QuoteStatus.AVAILABLE, QuoteQuality.REAL_TIME
    if normalized in _DELAYED_QUOTE_STATUSES:
        return QuoteStatus.DELAYED, QuoteQuality.DELAYED
    if normalized in _UNAVAILABLE_QUOTE_STATUSES:
        return QuoteStatus.UNAVAILABLE, QuoteQuality.UNKNOWN
    if normalized in _UNENTITLED_QUOTE_STATUSES:
        return QuoteStatus.UNENTITLED, QuoteQuality.UNKNOWN
    return QuoteStatus.UNKNOWN, QuoteQuality.UNKNOWN


def _quote_market_session(
    instrument: Instrument, row: dict[str, Any], state: dict[str, Any]
) -> tuple[MarketSession, str]:
    raw = _optional_text(row.get("market_session"))
    if raw is None:
        raw = _optional_text(state.get(f"market_{instrument.market.lower()}"))
    return normalize_market_session(instrument.market, raw), raw or "unknown"


def _quote_as_of(instrument: Instrument, value: object) -> datetime:
    try:
        timezone_name = _QUOTE_TIMEZONES[instrument.market]
    except KeyError as error:
        raise ValueError("Moomoo quote market is unsupported") from error
    return _opend_timestamp(value, timezone_name).astimezone(UTC)


def _normalize_quote_snapshot(
    instrument: Instrument,
    row: dict[str, Any],
    observed_at: datetime,
    market_state: dict[str, Any],
    maximum_age: timedelta,
    maximum_spread_bps: Decimal,
) -> QuoteSnapshot:
    raw_payload: dict[str, object] = {
        "snapshot": row,
        "market_state": market_state,
        "subscription_mode": "none",
    }
    fingerprint = _quote_fingerprint(raw_payload)
    try:
        status, quality = _quote_status(row)
        vendor_time = _optional_text(row.get("update_time"))
        if vendor_time is None:
            raise ValueError("Moomoo snapshot update time is required")
        as_of_at = _quote_as_of(instrument, vendor_time)
        if as_of_at > observed_at:
            raise ValueError("Moomoo snapshot time is after retrieval")
        last_price_value = _optional_text(row.get("last_price"))
        if status is QuoteStatus.AVAILABLE and last_price_value is None:
            raise ValueError("Moomoo entitled snapshot price is required")
        last_price = (
            _positive_decimal(last_price_value, "Moomoo snapshot price")
            if last_price_value is not None
            else None
        )
        bid_value = _optional_text(row.get("bid_price"))
        ask_value = _optional_text(row.get("ask_price"))
        if (bid_value is None) != (ask_value is None):
            raise ValueError("Moomoo snapshot bid and ask are incomplete")
        bid_price = _positive_decimal(bid_value, "Moomoo snapshot bid") if bid_value else None
        ask_price = _positive_decimal(ask_value, "Moomoo snapshot ask") if ask_value else None
        if bid_price is not None and ask_price is not None:
            midpoint = (bid_price + ask_price) / Decimal("2")
            spread = ask_price - bid_price
            if bid_price > ask_price:
                raise ValueError("Moomoo snapshot bid exceeds ask")
            order_book_status = "snapshot"
            order_book_as_of = as_of_at
        else:
            midpoint = None
            spread = None
            order_book_status = "absent"
            order_book_as_of = None
        if status is QuoteStatus.AVAILABLE and observed_at - as_of_at > maximum_age:
            status = QuoteStatus.STALE
        if status is QuoteStatus.AVAILABLE and midpoint is not None and spread is not None:
            spread_bps = spread / midpoint * Decimal("10000")
            if spread_bps > maximum_spread_bps:
                status = QuoteStatus.EXCESSIVE_SPREAD
        market_session, market_session_raw = _quote_market_session(instrument, row, market_state)
        return QuoteSnapshot(
            instrument,
            last_price,
            observed_at,
            quality,
            fingerprint,
            vendor_time,
            status,
            as_of_at,
            bid_price,
            ask_price,
            midpoint,
            spread,
            order_book_as_of,
            order_book_status,
            market_session,
            "none",
            fingerprint,
            raw_payload,
            market_session_raw,
        )
    except (KeyError, ValueError, ZoneInfoNotFoundError):
        return _malformed_snapshot(instrument, observed_at, row, "invalid_snapshot")


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ProviderError("Moomoo payload must be JSON serializable") from error


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _moomoo_date(value: object) -> date | None:
    text = _optional_text(value)
    if text is None:
        return None
    return date.fromisoformat(text.replace("/", "-"))


def _dividend_amount_per_share(value: object) -> tuple[Decimal | None, Currency | None]:
    statement = _optional_text(value)
    if statement is None or (match := _DIVIDEND_AMOUNT.search(statement)) is None:
        return None, None
    amount = _positive_decimal(match["amount"], "Moomoo dividend amount")
    return amount, Currency(match["currency"].upper())


def _identifier(row: dict[str, Any], field: str) -> str:
    value = str(row[field]).strip()
    if not value or value.lower() == "nan":
        raise ValueError(f"Moomoo {field} is required")
    return value


def _nonempty_strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ProviderError(f"{label} must be a sequence")
    normalized = tuple(value.strip() for value in values if isinstance(value, str) and value.strip())
    if len(normalized) != len(values) or len(set(normalized)) != len(normalized):
        raise ProviderError(f"{label} are invalid")
    return normalized


def _split_ratio(value: str) -> Decimal:
    before, separator, after = value.partition("->")
    if not separator or "->" in after:
        raise ValueError("Moomoo split rate is invalid")
    previous = _positive_decimal(before.strip(), "Moomoo split prior shares")
    current = _positive_decimal(after.strip(), "Moomoo split new shares")
    return current / previous


def _positive_decimal(value: object, label: str) -> Decimal:
    result = _nonnegative_decimal(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _nonnegative_decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"{label} must be decimal") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _opend_timestamp(value: object, timezone_name: str) -> datetime:
    try:
        timezone = ZoneInfo(timezone_name)
        parsed = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("Moomoo timestamp is invalid") from error
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ProviderError("Moomoo observation timestamp must be timezone-aware")
    return value.astimezone(UTC)
