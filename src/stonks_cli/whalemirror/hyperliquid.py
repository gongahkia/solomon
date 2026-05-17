from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Protocol

from stonks_cli.whalemirror.guards import evaluate_execution_guards
from stonks_cli.whalemirror.models import MirrorMode, Venue

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_EXCHANGE_URL = "https://api.hyperliquid.xyz/exchange"
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"


class HyperliquidClientError(RuntimeError):
    pass


class LiveExecutionBlocked(HyperliquidClientError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(", ".join(reasons))


class HttpSession(Protocol):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Any:
        ...


@dataclass(frozen=True)
class HyperliquidSignature:
    r: str
    s: str
    v: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HyperliquidOrderIntent:
    asset_index: int
    coin: str
    is_buy: bool
    limit_px: Decimal
    size: Decimal
    reduce_only: bool = False
    tif: str = "Alo"
    cloid: str | None = None

    def to_exchange_order(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "a": self.asset_index,
            "b": self.is_buy,
            "p": _decimal_str(self.limit_px),
            "s": _decimal_str(self.size),
            "r": self.reduce_only,
            "t": {"limit": {"tif": self.tif}},
        }
        if self.cloid:
            payload["c"] = self.cloid
        return payload


@dataclass(frozen=True)
class HyperliquidCancelIntent:
    asset_index: int
    oid: int | None = None
    cloid: str | None = None

    def to_exchange_cancel(self) -> dict[str, Any]:
        if self.oid is None and self.cloid is None:
            raise ValueError("cancel intent requires oid or cloid")
        payload: dict[str, Any] = {"a": self.asset_index}
        if self.oid is not None:
            payload["o"] = self.oid
        if self.cloid is not None:
            payload["cloid"] = self.cloid
        return payload


@dataclass(frozen=True)
class HyperliquidOpenOrder:
    coin: str
    side: str
    limit_px: Decimal
    size: Decimal
    oid: int
    timestamp_ms: int
    original_size: Decimal | None = None
    cloid: str | None = None


def build_order_action(order: HyperliquidOrderIntent | list[HyperliquidOrderIntent]) -> dict[str, Any]:
    orders = order if isinstance(order, list) else [order]
    if not orders:
        raise ValueError("at least one order is required")
    return {
        "type": "order",
        "orders": [o.to_exchange_order() for o in orders],
        "grouping": "na",
    }


def build_cancel_action(cancel: HyperliquidCancelIntent | list[HyperliquidCancelIntent]) -> dict[str, Any]:
    cancels = cancel if isinstance(cancel, list) else [cancel]
    if not cancels:
        raise ValueError("at least one cancel is required")
    return {
        "type": "cancel",
        "cancels": [c.to_exchange_cancel() for c in cancels],
    }


def build_open_orders_subscription(*, user: str, dex: str = "") -> dict[str, Any]:
    subscription = {"type": "openOrders", "user": user.lower()}
    if dex:
        subscription["dex"] = dex
    return {"method": "subscribe", "subscription": subscription}


def build_order_updates_subscription(*, user: str) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": {"type": "orderUpdates", "user": user.lower()}}


def build_ws_action_post_request(
    *,
    request_id: int,
    action: dict[str, Any],
    nonce: int,
    signature: HyperliquidSignature,
) -> dict[str, Any]:
    return {
        "method": "post",
        "id": request_id,
        "request": {
            "type": "action",
            "payload": {
                "action": action,
                "nonce": nonce,
                "signature": signature.to_dict(),
            },
        },
    }


def entry_price_guard_reasons(
    *,
    order: HyperliquidOrderIntent,
    mark_px: Decimal,
    max_slippage_bps: Decimal,
) -> list[str]:
    if mark_px <= 0:
        return ["invalid_mark_price"]
    if max_slippage_bps < 0:
        return ["invalid_max_slippage_bps"]

    tolerance = max_slippage_bps / Decimal("10000")
    if order.is_buy:
        max_buy = mark_px * (Decimal("1") + tolerance)
        if order.limit_px > max_buy:
            return [f"entry_price_above_mark_guard:{_decimal_str(order.limit_px)}>{_decimal_str(max_buy)}"]
    else:
        min_sell = mark_px * (Decimal("1") - tolerance)
        if order.limit_px < min_sell:
            return [f"entry_price_below_mark_guard:{_decimal_str(order.limit_px)}<{_decimal_str(min_sell)}"]
    return []


class HyperliquidOrderClient:
    def __init__(
        self,
        *,
        session: HttpSession | None = None,
        info_url: str = HYPERLIQUID_INFO_URL,
        exchange_url: str = HYPERLIQUID_EXCHANGE_URL,
        timeout: float = 10.0,
    ) -> None:
        if session is None:
            import requests

            session = requests.Session()
        self._session = session
        self.info_url = info_url
        self.exchange_url = exchange_url
        self.timeout = timeout

    def create_order(
        self,
        order: HyperliquidOrderIntent | list[HyperliquidOrderIntent],
        *,
        mode: MirrorMode | str = MirrorMode.DRY_RUN,
        nonce: int | None = None,
        signature: HyperliquidSignature | None = None,
        extra_guard_reasons: list[str] | None = None,
        heartbeat_ok: bool | None = None,
        emergency_stop_active: bool = False,
        consensus_approved: bool | None = None,
    ) -> dict[str, Any]:
        return self.submit_exchange_action(
            build_order_action(order),
            mode=mode,
            nonce=nonce,
            signature=signature,
            extra_guard_reasons=extra_guard_reasons,
            heartbeat_ok=heartbeat_ok,
            emergency_stop_active=emergency_stop_active,
            consensus_approved=consensus_approved,
        )

    def cancel_order(
        self,
        cancel: HyperliquidCancelIntent | list[HyperliquidCancelIntent],
        *,
        mode: MirrorMode | str = MirrorMode.DRY_RUN,
        nonce: int | None = None,
        signature: HyperliquidSignature | None = None,
        extra_guard_reasons: list[str] | None = None,
        heartbeat_ok: bool | None = None,
        emergency_stop_active: bool = False,
        consensus_approved: bool | None = None,
    ) -> dict[str, Any]:
        return self.submit_exchange_action(
            build_cancel_action(cancel),
            mode=mode,
            nonce=nonce,
            signature=signature,
            extra_guard_reasons=extra_guard_reasons,
            heartbeat_ok=heartbeat_ok,
            emergency_stop_active=emergency_stop_active,
            consensus_approved=consensus_approved,
        )

    def submit_exchange_action(
        self,
        action: dict[str, Any],
        *,
        mode: MirrorMode | str,
        nonce: int | None = None,
        signature: HyperliquidSignature | None = None,
        extra_guard_reasons: list[str] | None = None,
        heartbeat_ok: bool | None = None,
        emergency_stop_active: bool = False,
        consensus_approved: bool | None = None,
    ) -> dict[str, Any]:
        resolved_mode = MirrorMode(mode)
        guard_reasons = evaluate_execution_guards(
            venue=Venue.HYPERLIQUID,
            mode=resolved_mode,
            heartbeat_ok=heartbeat_ok,
            emergency_stop_active=emergency_stop_active,
            consensus_approved=consensus_approved,
        )
        guard_reasons.extend(extra_guard_reasons or [])
        if resolved_mode is not MirrorMode.LIVE:
            return {"status": "dry_run", "request": {"action": action}}
        if guard_reasons:
            raise LiveExecutionBlocked(guard_reasons)
        if nonce is None or signature is None:
            raise LiveExecutionBlocked(["missing_signed_hyperliquid_payload"])

        request = {"action": action, "nonce": nonce, "signature": signature.to_dict()}
        response = self._session.post(self.exchange_url, json=request, timeout=self.timeout)
        return _json_response(response)

    def build_ws_order_post(
        self,
        order: HyperliquidOrderIntent | list[HyperliquidOrderIntent],
        *,
        request_id: int,
        mode: MirrorMode | str = MirrorMode.DRY_RUN,
        nonce: int | None = None,
        signature: HyperliquidSignature | None = None,
        extra_guard_reasons: list[str] | None = None,
        heartbeat_ok: bool | None = None,
        emergency_stop_active: bool = False,
        consensus_approved: bool | None = None,
    ) -> dict[str, Any]:
        action = build_order_action(order)
        resolved_mode = MirrorMode(mode)
        guard_reasons = evaluate_execution_guards(
            venue=Venue.HYPERLIQUID,
            mode=resolved_mode,
            heartbeat_ok=heartbeat_ok,
            emergency_stop_active=emergency_stop_active,
            consensus_approved=consensus_approved,
        )
        guard_reasons.extend(extra_guard_reasons or [])
        if resolved_mode is not MirrorMode.LIVE:
            return {"status": "dry_run", "request": {"action": action}}
        if guard_reasons:
            raise LiveExecutionBlocked(guard_reasons)
        if nonce is None or signature is None:
            raise LiveExecutionBlocked(["missing_signed_hyperliquid_payload"])
        return build_ws_action_post_request(
            request_id=request_id,
            action=action,
            nonce=nonce,
            signature=signature,
        )

    def sync_open_orders(self, *, user: str, dex: str = "") -> list[HyperliquidOpenOrder]:
        request = {"type": "openOrders", "user": user.lower()}
        if dex:
            request["dex"] = dex
        response = self._session.post(self.info_url, json=request, timeout=self.timeout)
        payload = _json_response(response)
        if not isinstance(payload, list):
            raise HyperliquidClientError("openOrders response must be a list")
        return [_parse_open_order(row) for row in payload]


def _parse_open_order(row: dict[str, Any]) -> HyperliquidOpenOrder:
    return HyperliquidOpenOrder(
        coin=str(row["coin"]),
        side=str(row["side"]),
        limit_px=Decimal(str(row["limitPx"])),
        size=Decimal(str(row["sz"])),
        oid=int(row["oid"]),
        timestamp_ms=int(row["timestamp"]),
        original_size=Decimal(str(row["origSz"])) if row.get("origSz") is not None else None,
        cloid=str(row["cloid"]) if row.get("cloid") is not None else None,
    )


def _json_response(response: Any) -> Any:
    status_code = int(getattr(response, "status_code", 200))
    try:
        payload = response.json()
    except Exception as e:
        raise HyperliquidClientError(f"invalid json response: {e}") from e
    if status_code >= 400:
        raise HyperliquidClientError(f"hyperliquid http {status_code}: {payload}")
    return payload


def _decimal_str(value: Decimal) -> str:
    return format(value.normalize(), "f")
