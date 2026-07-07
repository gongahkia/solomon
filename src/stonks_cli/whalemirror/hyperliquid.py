from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from stonks_cli.whalemirror.guards import evaluate_execution_guards
from stonks_cli.whalemirror.models import (
    BasisSnapshot,
    CarryOpportunity,
    CarryQuote,
    FundingSnapshot,
    MirrorMode,
    Venue,
)

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


@dataclass(frozen=True)
class HyperliquidCarryInput:
    asset: str
    quote: CarryQuote
    funding: FundingSnapshot | None
    basis: BasisSnapshot | None
    metadata: dict[str, Any]
    source_health: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "basis": self.basis.to_dict() if self.basis else None,
            "funding": self.funding.to_dict() if self.funding else None,
            "metadata": self.metadata,
            "quote": self.quote.to_dict(),
            "source_health": self.source_health,
        }


@dataclass(frozen=True)
class CarryInputCompleteness:
    ok: bool
    required_fields_missing: list[str]
    stale_fields: list[str]
    cross_timestamp_fields: list[str]

    @property
    def caveats(self) -> list[str]:
        return self.required_fields_missing + self.stale_fields + self.cross_timestamp_fields


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
        payload = self._post_info(request)
        if not isinstance(payload, list):
            raise HyperliquidClientError("openOrders response must be a list")
        return [_parse_open_order(row) for row in payload]

    def fetch_all_mids(self, *, dex: str = "") -> dict[str, float]:
        payload = self._post_info(_info_request("allMids", dex=dex))
        mids = payload.get("mids") if isinstance(payload, dict) and isinstance(payload.get("mids"), dict) else payload
        if not isinstance(mids, dict):
            raise HyperliquidClientError("allMids response must be an object")
        return {str(coin): float(str(mid)) for coin, mid in mids.items()}

    def fetch_meta_and_asset_ctxs(self, *, dex: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return _split_meta_and_ctxs(self._post_info(_info_request("metaAndAssetCtxs", dex=dex)), "metaAndAssetCtxs")

    def fetch_spot_meta_and_asset_ctxs(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return _split_meta_and_ctxs(self._post_info({"type": "spotMetaAndAssetCtxs"}), "spotMetaAndAssetCtxs")

    def fetch_funding_history(self, *, coin: str, start_time: int, end_time: int | None = None) -> list[dict[str, Any]]:
        request: dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": start_time}
        if end_time is not None:
            request["endTime"] = end_time
        payload = self._post_info(request)
        if not isinstance(payload, list):
            raise HyperliquidClientError("fundingHistory response must be a list")
        return [dict(row) for row in payload if isinstance(row, dict)]

    def fetch_predicted_fundings(self) -> Any:
        return self._post_info({"type": "predictedFundings"})

    def fetch_carry_inputs(
        self,
        *,
        assets: tuple[str, ...] = ("BTC", "ETH"),
        dex: str = "",
        timestamp_utc: str | None = None,
    ) -> list[HyperliquidCarryInput]:
        timestamp = timestamp_utc or _iso(_now())
        mids = self.fetch_all_mids(dex=dex)
        perp_meta, perp_ctxs = self.fetch_meta_and_asset_ctxs(dex=dex)
        spot_meta, spot_ctxs = self.fetch_spot_meta_and_asset_ctxs()
        predicted_fundings = self.fetch_predicted_fundings()
        return [
            _build_carry_input(
                asset=asset,
                mids=mids,
                perp_meta=perp_meta,
                perp_ctxs=perp_ctxs,
                spot_meta=spot_meta,
                spot_ctxs=spot_ctxs,
                predicted_fundings=predicted_fundings,
                timestamp_utc=timestamp,
            )
            for asset in assets
        ]

    def _post_info(self, request: dict[str, Any]) -> Any:
        response = self._session.post(self.info_url, json=request, timeout=self.timeout)
        return _json_response(response)


def validate_carry_input_completeness(
    inputs: HyperliquidCarryInput,
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
    max_timestamp_skew_seconds: float = 10.0,
) -> CarryInputCompleteness:
    now = now or _now()
    required_missing = _missing_required_fields(inputs)
    stale_fields = _stale_fields(inputs, now=now, max_age_seconds=max_age_seconds)
    cross_timestamp_fields = _cross_timestamp_fields(inputs, max_timestamp_skew_seconds=max_timestamp_skew_seconds)
    return CarryInputCompleteness(
        ok=not required_missing and not stale_fields and not cross_timestamp_fields,
        required_fields_missing=required_missing,
        stale_fields=stale_fields,
        cross_timestamp_fields=cross_timestamp_fields,
    )


def blocked_carry_opportunity(
    inputs: HyperliquidCarryInput,
    validation: CarryInputCompleteness | None = None,
) -> CarryOpportunity:
    validation = validation or validate_carry_input_completeness(inputs)
    return CarryOpportunity(
        asset=inputs.asset,
        venue=Venue.HYPERLIQUID,
        direction="blocked",
        net_apr=0.0,
        gross_apr=0.0,
        fee_bps=0.0,
        slippage_bps=0.0,
        buffer_bps=0.0,
        required_fields_missing=validation.caveats,
    )


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


def _info_request(request_type: str, *, dex: str = "") -> dict[str, Any]:
    request = {"type": request_type}
    if dex:
        request["dex"] = dex
    return request


def _split_meta_and_ctxs(payload: Any, name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, list) or len(payload) != 2:
        raise HyperliquidClientError(f"{name} response must be [metadata, contexts]")
    meta, ctxs = payload
    if not isinstance(meta, dict) or not isinstance(ctxs, list):
        raise HyperliquidClientError(f"{name} response must be [object, list]")
    return meta, [dict(ctx) for ctx in ctxs if isinstance(ctx, dict)]


def _build_carry_input(
    *,
    asset: str,
    mids: dict[str, float],
    perp_meta: dict[str, Any],
    perp_ctxs: list[dict[str, Any]],
    spot_meta: dict[str, Any],
    spot_ctxs: list[dict[str, Any]],
    predicted_fundings: Any,
    timestamp_utc: str,
) -> HyperliquidCarryInput:
    normalized_asset = asset.upper()
    perp_row, perp_ctx = _perp_meta_and_ctx(normalized_asset, perp_meta, perp_ctxs)
    spot_pair, spot_ctx = _spot_pair_and_ctx(normalized_asset, spot_meta, spot_ctxs)
    perp_mid = _float_or_none(mids.get(normalized_asset))
    spot_mid = _spot_mid(normalized_asset, mids, spot_pair, spot_ctx)
    mark_mid = _float_or_none((perp_ctx or {}).get("markPx"))
    oracle_mid = _float_or_none((perp_ctx or {}).get("oraclePx"))
    hourly_rate = _float_or_none((perp_ctx or {}).get("funding"))
    quote = CarryQuote(
        venue=Venue.HYPERLIQUID,
        asset=normalized_asset,
        spot_mid=spot_mid,
        perp_mid=perp_mid,
        oracle_mid=oracle_mid,
        mark_mid=mark_mid,
        timestamp=timestamp_utc,
        source_health=_quote_source_health(spot_mid=spot_mid, perp_mid=perp_mid, oracle_mid=oracle_mid, mark_mid=mark_mid),
    )
    funding = (
        FundingSnapshot(
            asset=normalized_asset,
            venue=Venue.HYPERLIQUID,
            hourly_rate=hourly_rate,
            annualized_rate=hourly_rate * 24 * 365,
            next_funding_time=None,
            premium_index=_float_or_none((perp_ctx or {}).get("premium")),
            timestamp=timestamp_utc,
        )
        if hourly_rate is not None
        else None
    )
    basis = _basis_snapshot(asset=normalized_asset, spot_mid=spot_mid, perp_mid=perp_mid, timestamp_utc=timestamp_utc)
    metadata = {
        "perp": perp_row or {},
        "perp_ctx": perp_ctx or {},
        "predicted_funding": _predicted_funding_for_asset(normalized_asset, predicted_fundings),
        "spot": spot_pair or {},
        "spot_ctx": spot_ctx or {},
    }
    source_health = {
        "all_mids": "ok" if mids else "missing",
        "perp_context": "ok" if perp_ctx else "missing",
        "perp_metadata": "ok" if perp_row else "missing",
        "predicted_funding": "ok" if metadata["predicted_funding"] else "missing",
        "spot_context": "ok" if spot_ctx else "missing",
        "spot_metadata": "ok" if spot_pair else "missing",
    }
    return HyperliquidCarryInput(
        asset=normalized_asset,
        quote=quote,
        funding=funding,
        basis=basis,
        metadata=metadata,
        source_health=source_health,
    )


def _perp_meta_and_ctx(asset: str, meta: dict[str, Any], ctxs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    universe = meta.get("universe") if isinstance(meta.get("universe"), list) else []
    for index, row in enumerate(universe):
        if isinstance(row, dict) and str(row.get("name", "")).upper() == asset:
            return row, ctxs[index] if index < len(ctxs) else None
    return None, None


def _spot_pair_and_ctx(asset: str, meta: dict[str, Any], ctxs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    universe = meta.get("universe") if isinstance(meta.get("universe"), list) else []
    tokens = meta.get("tokens") if isinstance(meta.get("tokens"), list) else []
    token_names = {int(token["index"]): str(token["name"]).upper() for token in tokens if isinstance(token, dict) and "index" in token}
    for index, row in enumerate(universe):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).upper()
        pair_tokens = row.get("tokens") if isinstance(row.get("tokens"), list) else []
        base_name = token_names.get(int(pair_tokens[0])) if pair_tokens else ""
        if name in {f"{asset}/USDC", f"U{asset}/USDC"} or base_name in {asset, f"U{asset}"}:
            return row, ctxs[index] if index < len(ctxs) else None
    return None, None


def _spot_mid(asset: str, mids: dict[str, float], spot_pair: dict[str, Any] | None, spot_ctx: dict[str, Any] | None) -> float | None:
    candidates = [f"{asset}/USDC", f"U{asset}/USDC"]
    if spot_pair:
        candidates.insert(0, str(spot_pair.get("name", "")))
    for candidate in candidates:
        if candidate in mids:
            return _float_or_none(mids[candidate])
    return _float_or_none((spot_ctx or {}).get("midPx"))


def _basis_snapshot(*, asset: str, spot_mid: float | None, perp_mid: float | None, timestamp_utc: str) -> BasisSnapshot | None:
    if spot_mid is None or perp_mid is None or spot_mid <= 0:
        return None
    basis_abs = perp_mid - spot_mid
    basis_pct = basis_abs / spot_mid
    return BasisSnapshot(
        asset=asset,
        spot_mid=spot_mid,
        perp_mid=perp_mid,
        basis_abs=basis_abs,
        basis_pct=basis_pct,
        annualized_basis=0.0,
        timestamp=timestamp_utc,
    )


def _predicted_funding_for_asset(asset: str, payload: Any) -> Any:
    if isinstance(payload, dict):
        return payload.get(asset) or payload.get(asset.upper()) or payload.get(asset.lower())
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and str(row.get("coin") or row.get("asset") or "").upper() == asset:
                return row
            if isinstance(row, list) and row and str(row[0]).upper() == asset:
                return row
    return None


def _quote_source_health(*, spot_mid: float | None, perp_mid: float | None, oracle_mid: float | None, mark_mid: float | None) -> str:
    missing = [
        name
        for name, value in {
            "mark_mid": mark_mid,
            "oracle_mid": oracle_mid,
            "perp_mid": perp_mid,
            "spot_mid": spot_mid,
        }.items()
        if value is None
    ]
    return "ok" if not missing else f"missing:{','.join(missing)}"


def _missing_required_fields(inputs: HyperliquidCarryInput) -> list[str]:
    missing = []
    if inputs.quote.spot_mid is None:
        missing.append("quote.spot_mid")
    if inputs.quote.perp_mid is None:
        missing.append("quote.perp_mid")
    if inputs.quote.oracle_mid is None:
        missing.append("quote.oracle_mid")
    if inputs.quote.mark_mid is None:
        missing.append("quote.mark_mid")
    if inputs.funding is None:
        missing.append("funding")
    if inputs.basis is None:
        missing.append("basis")
    if not inputs.metadata.get("perp"):
        missing.append("metadata.perp")
    if not inputs.metadata.get("spot"):
        missing.append("metadata.spot")
    return missing


def _stale_fields(inputs: HyperliquidCarryInput, *, now: datetime, max_age_seconds: float) -> list[str]:
    stale = []
    for name, timestamp in _input_timestamps(inputs).items():
        age = (now - _parse_iso(timestamp)).total_seconds()
        if age > max_age_seconds:
            stale.append(f"stale:{name}:{int(age)}s>{int(max_age_seconds)}s")
    return stale


def _cross_timestamp_fields(inputs: HyperliquidCarryInput, *, max_timestamp_skew_seconds: float) -> list[str]:
    timestamps = _input_timestamps(inputs)
    if len(timestamps) < 2:
        return []
    parsed = {name: _parse_iso(timestamp) for name, timestamp in timestamps.items()}
    skew = (max(parsed.values()) - min(parsed.values())).total_seconds()
    if skew <= max_timestamp_skew_seconds:
        return []
    names = ",".join(sorted(parsed))
    return [f"cross_timestamp:{names}:{int(skew)}s>{int(max_timestamp_skew_seconds)}s"]


def _input_timestamps(inputs: HyperliquidCarryInput) -> dict[str, str]:
    timestamps = {"quote": inputs.quote.timestamp}
    if inputs.funding is not None:
        timestamps["funding"] = inputs.funding.timestamp
    if inputs.basis is not None:
        timestamps["basis"] = inputs.basis.timestamp
    return timestamps


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(str(value))


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
