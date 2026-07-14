from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from stonks_cli.vnext.broker_submission import require_read_only_broker_method
from stonks_cli.vnext.errors import VNextExecutionDeniedError, VNextExternalDataError


@dataclass(frozen=True)
class RecordedOpenDCall:
    method: str
    args: tuple[object, ...]
    kwargs: tuple[tuple[str, object], ...]
    response: object

    def __post_init__(self) -> None:
        try:
            require_read_only_broker_method(self.method)
        except (TypeError, ValueError, VNextExecutionDeniedError) as error:
            raise ValueError("recorded OpenD method must be a non-mutating name") from error
        if not isinstance(self.args, tuple) or not isinstance(self.kwargs, tuple):
            raise TypeError("recorded OpenD arguments must be tuples")
        if any(not isinstance(key, str) for key, _ in self.kwargs) or len({key for key, _ in self.kwargs}) != len(self.kwargs):
            raise ValueError("recorded OpenD keyword arguments are invalid")


@dataclass(frozen=True)
class RecordedOpenDFixtureAdapter:
    host: str
    port: int
    calls: tuple[RecordedOpenDCall, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host or not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("recorded OpenD endpoint is invalid")
        if not isinstance(self.calls, tuple) or not all(isinstance(call, RecordedOpenDCall) for call in self.calls):
            raise TypeError("recorded OpenD calls are required")

    def context_factory(self, host: str, port: int) -> RecordedOpenDContext:
        if (host, port) != (self.host, self.port):
            raise VNextExternalDataError("recorded OpenD endpoint does not match")
        return RecordedOpenDContext(self.calls)


class RecordedOpenDContext:
    def __init__(self, calls: tuple[RecordedOpenDCall, ...]) -> None:
        self._calls = calls
        self._next_index = 0
        self._closed = False

    def __getattr__(self, method: str) -> Callable[..., object]:
        require_read_only_broker_method(method)
        return lambda *args, **kwargs: self._invoke(method, args, kwargs)

    def close(self) -> None:
        if self._closed:
            raise VNextExternalDataError("recorded OpenD context is already closed")
        self._closed = True
        if self._next_index != len(self._calls):
            raise VNextExternalDataError("recorded OpenD fixture has unconsumed calls")

    def _invoke(self, method: str, args: tuple[object, ...], kwargs: dict[str, object]) -> object:
        if self._closed or self._next_index >= len(self._calls):
            raise VNextExternalDataError("recorded OpenD fixture has no matching call")
        recorded = self._calls[self._next_index]
        if (method, args, tuple(kwargs.items())) != (recorded.method, recorded.args, recorded.kwargs):
            raise VNextExternalDataError("recorded OpenD call does not match fixture")
        self._next_index += 1
        return recorded.response
