from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module, metadata, util
from typing import Any

from stonks_cli.errors import ProviderError
from stonks_cli.plugins import Capability, PluginManifest, register_builtin_provider

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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
        self, endpoint: OpenDConnection, context_factory: Callable[[str, int], Any]
    ) -> None:
        self.endpoint = endpoint
        self.context_factory = context_factory

    @classmethod
    def from_installed_sdk(cls, endpoint: OpenDConnection) -> MoomooReadOnlyProvider:
        try:
            module: Any = import_module("moomoo")
            context_class = module.OpenSecTradeContext
        except (AttributeError, ImportError) as error:
            raise ProviderError("install with: uv sync --extra moomoo") from error

        def factory(host: str, port: int) -> Any:
            return context_class(host=host, port=port)

        return cls(endpoint, factory)

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

    def positions(self, account_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(_records(self._call("position_list_query", acc_id=account_id)))

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

    def _call(self, method: str, **kwargs: Any) -> Any:
        if any(
            part in method.lower() for part in ("order", "unlock", "modify", "place", "cancel")
        ) and method not in {
            "history_order_list_query",
        }:
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
