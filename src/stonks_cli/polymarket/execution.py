from __future__ import annotations

from dataclasses import asdict
import os
from dataclasses import dataclass
from typing import Protocol

from stonks_cli.config import AppConfig
from stonks_cli.polymarket.journal import append_journal
from stonks_cli.polymarket.paper import paper_buy, paper_sell


@dataclass(frozen=True)
class ExecutionOrder:
    token_id: str
    market_id: str
    slug: str | None
    outcome: str | None
    side: str
    price: float
    shares: float
    target_price: float | None = None
    stop_price: float | None = None
    reason: str | None = None


def validate_execution_order(order: ExecutionOrder) -> None:
    if not order.token_id.strip():
        raise ValueError("token_id must be non-empty")
    if not order.market_id.strip():
        raise ValueError("market_id must be non-empty")
    if order.side.upper() not in {"BUY", "SELL"}:
        raise ValueError(f"unsupported side: {order.side}")
    if order.price <= 0 or order.price >= 1:
        raise ValueError("price must be between 0 and 1")
    if order.shares <= 0:
        raise ValueError("shares must be positive")


class Executor(Protocol):
    def execute(self, order: ExecutionOrder) -> dict[str, object]: ...


class PaperExecutor:
    def execute(self, order: ExecutionOrder) -> dict[str, object]:
        validate_execution_order(order)
        if order.side.upper() == "BUY":
            result = paper_buy(
                token_id=order.token_id,
                market_id=order.market_id,
                slug=order.slug,
                outcome=order.outcome,
                shares=order.shares,
                price=order.price,
                target_price=order.target_price,
                stop_price=order.stop_price,
                thesis=order.reason,
                reason=order.reason,
            )
        else:
            result = paper_sell(token_id=order.token_id, shares=order.shares, price=order.price, reason=order.reason)
        append_journal("paper_execution", order=asdict(order), result=result)
        return result


class LiveExecutor:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg

    def execute(self, order: ExecutionOrder) -> dict[str, object]:
        validate_execution_order(order)
        try:
            from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, PartialCreateOrderOptions, Side
        except Exception as e:
            raise ImportError("live trading requires optional dependency `py-clob-client-v2`") from e

        private_key = os.getenv(self._cfg.polymarket.private_key_env or "POLYMARKET_PRIVATE_KEY")
        if not private_key:
            raise ValueError(
                f"missing private key in environment variable {self._cfg.polymarket.private_key_env or 'POLYMARKET_PRIVATE_KEY'}"
            )

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=self._cfg.polymarket.chain_id,
            key=private_key,
        )
        creds = client.create_or_derive_api_key()
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=self._cfg.polymarket.chain_id,
            key=private_key,
            creds=creds,
        )
        side = Side.BUY if order.side.upper() == "BUY" else Side.SELL
        response = client.create_and_post_order(
            order_args=OrderArgs(
                token_id=order.token_id,
                price=order.price,
                side=side,
                size=order.shares,
            ),
            options=PartialCreateOrderOptions(tick_size="0.01"),
            order_type=OrderType.GTC,
        )
        result = {
            "mode": "live",
            "response": response,
            "order": order.__dict__,
        }
        append_journal("live_execution", order=asdict(order), result=result)
        return result


def executor_for_config(cfg: AppConfig) -> Executor:
    return PaperExecutor() if cfg.polymarket.paper else LiveExecutor(cfg)
