from __future__ import annotations

from dataclasses import dataclass

from stonks_cli.vnext.errors import VNextExecutionDeniedError

_LOCAL_OPEND_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class MoomooOpenDProcessContract:
    host: str
    port: int
    operator_starts_gateway: bool = True
    operator_logs_in_gateway: bool = True
    cli_may_start_gateway: bool = False
    cli_may_unlock_trading: bool = False
    cli_may_submit_orders: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or self.host.lower() not in _LOCAL_OPEND_HOSTS:
            raise ValueError("OpenD process contract requires a local host")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("OpenD process contract requires a valid port")
        if not self.operator_starts_gateway or not self.operator_logs_in_gateway:
            raise ValueError("OpenD process contract requires operator-managed startup and login")
        if self.cli_may_start_gateway or self.cli_may_unlock_trading or self.cli_may_submit_orders:
            raise VNextExecutionDeniedError("OpenD contract prohibits CLI process, unlock, and order actions")

    def to_data(self) -> dict[str, object]:
        return {
            "host": self.host.lower(),
            "port": self.port,
            "operator_starts_gateway": self.operator_starts_gateway,
            "operator_logs_in_gateway": self.operator_logs_in_gateway,
            "cli_may_start_gateway": self.cli_may_start_gateway,
            "cli_may_unlock_trading": self.cli_may_unlock_trading,
            "cli_may_submit_orders": self.cli_may_submit_orders,
        }
