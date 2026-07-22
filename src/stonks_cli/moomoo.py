from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib import import_module, metadata, util
from typing import Any

from stonks_cli.errors import ProviderError
from stonks_cli.market_data import DailyPrice
from stonks_cli.plugins import Capability, PluginManifest, register_builtin_provider
from stonks_cli.types import Instrument

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_READ_METHODS = frozenset(
    {
        "get_acc_list",
        "accinfo_query",
        "get_acc_cash_flow",
        "position_list_query",
        "history_order_list_query",
        "history_deal_list_query",
    }
)


@dataclass(frozen=True)
class OpenDConnection:
    host: str = "127.0.0.1"
    port: int = 11111

    def __post_init__(self) -> None:
        if self.host.lower() not in _LOCAL_HOSTS or not 1 <= self.port <= 65535:
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
    ) -> None:
        self.endpoint = endpoint
        self.context_factory = context_factory
        self.quote_context_factory = quote_context_factory

    @classmethod
    def from_installed_sdk(cls, endpoint: OpenDConnection) -> MoomooReadOnlyProvider:
        try:
            module: Any = import_module("moomoo")
            context_class = module.OpenSecTradeContext
            quote_context_class = module.OpenQuoteContext
        except (AttributeError, ImportError) as error:
            raise ProviderError("install with: uv sync --extra moomoo") from error

        def factory(host: str, port: int) -> Any:
            return context_class(host=host, port=port)

        def quote_factory(host: str, port: int) -> Any:
            return quote_context_class(host=host, port=port)

        return cls(endpoint, factory, quote_factory)

    @staticmethod
    def sdk_version() -> str | None:
        try:
            version = metadata.version("moomoo-api")
        except metadata.PackageNotFoundError:
            return None
        return version if util.find_spec("moomoo") is not None else None

    def accounts(self) -> tuple[MoomooAccount, ...]:
        records = self._call("get_acc_list")
        parsed: list[MoomooAccount] = []
        for row in _records(records):
            try:
                parsed.append(
                    MoomooAccount(str(row["acc_id"]), int(row["acc_index"]), str(row["trd_env"]))
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderError("malformed Moomoo account record") from error
        if len({item.account_id for item in parsed}) != len(parsed):
            raise ProviderError("duplicate Moomoo account IDs")
        return tuple(sorted(parsed, key=lambda item: (item.account_index, item.account_id)))

    @classmethod
    def probe(cls, endpoint: OpenDConnection) -> OpenDProbe:
        provider = cls.from_installed_sdk(endpoint)
        return OpenDProbe(endpoint, provider.sdk_version(), len(provider.accounts()))

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
            for row in rows:
                try:
                    session_date = date.fromisoformat(str(row["time_key"]).split()[0])
                    close = Decimal(str(row["close"]))
                except (KeyError, ValueError) as error:
                    raise ProviderError("malformed Moomoo daily bar") from error
                prices.append(DailyPrice(instrument, session_date, close, source_hash))
        return tuple(sorted(prices, key=lambda item: (item.instrument.key, item.session_date)))

    def _historical_bars(
        self, instrument: Instrument, start: date, end: date
    ) -> list[dict[str, Any]]:
        if self.quote_context_factory is None:
            raise ProviderError("Moomoo quote context is unavailable")
        context = self.quote_context_factory(self.endpoint.host, self.endpoint.port)
        rows: list[dict[str, Any]] = []
        page_key: Any = None
        try:
            while True:
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
                page_key = response[2]
                if page_key is None:
                    return rows
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("Moomoo read failed:request_history_kline") from error
        finally:
            close = getattr(context, "close", None)
            if not callable(close):
                raise ProviderError("Moomoo quote context cannot be closed")
            close()

    def _call(self, method: str, **kwargs: Any) -> Any:
        if method not in _READ_METHODS:
            raise ProviderError(f"Moomoo method is not read-only:{method}")
        context = self.context_factory(self.endpoint.host, self.endpoint.port)
        try:
            call = getattr(context, method, None)
            if not callable(call):
                raise ProviderError(f"Moomoo context does not support:{method}")
            response = call(**kwargs)
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
