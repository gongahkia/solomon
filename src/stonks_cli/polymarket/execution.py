from __future__ import annotations

from dataclasses import asdict
import os
from dataclasses import dataclass
from typing import Protocol

from stonks_cli.config import AppConfig
from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.journal import append_journal
from stonks_cli.polymarket.lifecycle import LiveOrderManager, build_live_order_request
from stonks_cli.polymarket.paper import paper_buy, paper_sell
from stonks_cli.polymarket.stream import snapshot_from_book


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
        self._market_client = PolymarketClient()
        self._order_manager = LiveOrderManager(cfg)

    def _build_client(self):
        try:
            from py_clob_client_v2 import ClobClient
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
        return ClobClient(
            host="https://clob.polymarket.com",
            chain_id=self._cfg.polymarket.chain_id,
            key=private_key,
            creds=creds,
        )

    def cancel_stale_orders(self) -> list[dict[str, object]]:
        actions = self._order_manager.stale_cancels()
        if not actions:
            return []
        client = self._build_client()
        results: list[dict[str, object]] = []
        for action in actions:
            response = _cancel_live_order(client, action.order_id)
            updated = self._order_manager.mark_cancelled(action.order_id, reason=action.reason or "stale_open_order")
            result = {
                "mode": "live",
                "action": "CANCEL",
                "token_id": action.token_id,
                "order_id": action.order_id,
                "reason": action.reason,
                "response": response,
                "updated": asdict(updated) if updated is not None else None,
            }
            append_journal("live_stale_cancel", result=result)
            results.append(result)
        return results

    def execute(self, order: ExecutionOrder) -> dict[str, object]:
        validate_execution_order(order)
        try:
            from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, PartialCreateOrderOptions, Side
        except Exception as e:
            raise ImportError("live trading requires optional dependency `py-clob-client-v2`") from e
        client = self._build_client()
        book = self._market_client.get_book(order.token_id)
        snapshot = snapshot_from_book(book)
        live_request = build_live_order_request(self._cfg, order, snapshot)
        side = Side.BUY if order.side.upper() == "BUY" else Side.SELL
        pre_submit_cancels = self.cancel_stale_orders()
        response = client.create_and_post_order(
            order_args=OrderArgs(
                token_id=live_request.token_id,
                price=live_request.price,
                side=side,
                size=live_request.shares,
            ),
            options=PartialCreateOrderOptions(tick_size=str(live_request.tick_size)),
            order_type=OrderType.GTC,
        )
        order_id = _extract_live_order_id(response)
        if order_id:
            self._order_manager.register_submitted(order_id, live_request)
        result = {
            "mode": "live",
            "response": response,
            "order": order.__dict__,
            "request": asdict(live_request),
            "snapshot": asdict(snapshot),
            "order_id": order_id,
            "stale_cancels": pre_submit_cancels,
        }
        append_journal("live_execution", order=asdict(order), result=result)
        return result


def executor_for_config(cfg: AppConfig) -> Executor:
    return PaperExecutor() if cfg.polymarket.paper else LiveExecutor(cfg)


def _extract_live_order_id(response: object) -> str | None:
    if isinstance(response, dict):
        for key in ("orderID", "orderId", "id"):
            value = response.get(key)
            if value not in (None, ""):
                return str(value)
    for key in ("orderID", "orderId", "id"):
        value = getattr(response, key, None)
        if value not in (None, ""):
            return str(value)
    return None


def _cancel_live_order(client: object, order_id: str) -> object:
    for method_name, kwargs in (
        ("cancel", {"order_id": order_id}),
        ("cancel_order", {"order_id": order_id}),
        ("cancel_order", {"id": order_id}),
        ("cancel_orders", {"order_ids": [order_id]}),
    ):
        method = getattr(client, method_name, None)
        if method is None:
            continue
        try:
            return method(**kwargs)
        except TypeError:
            continue
    raise AttributeError("live client does not expose a supported cancel method")
