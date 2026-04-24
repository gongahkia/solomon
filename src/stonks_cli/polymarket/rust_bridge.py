from __future__ import annotations

import atexit
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import time
from typing import Any

from stonks_cli.config import AppConfig


class RustHotPathSession:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._workspace = Path(__file__).resolve().parents[3] / "rust"
        self._binary = self._workspace / "target" / "debug" / "stonks-polymarket-hotpath"
        self._state_path = self._workspace.parent / ".cache" / "polymarket_rust_hotpath.state"
        self._proc: subprocess.Popen[str] | None = None
        atexit.register(self.close)

    def ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        cmd = (
            ["cargo", "run", "--quiet", "--bin", "stonks-polymarket-hotpath", "--", "daemon"]
            if self._cfg.polymarket.rust_hotpath_use_cargo or not self._binary.exists()
            else [str(self._binary), "daemon"]
        )
        self._proc = subprocess.Popen(
            cmd,
            cwd=self._workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self._state_path.exists():
            self._command(f"LOAD path={self._state_path}")

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._save()
        except Exception:
            pass
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        self._proc.terminate()
        self._proc = None

    def status(self) -> dict[str, str]:
        return self._command("STATUS")

    def update_book(
        self,
        *,
        token_id: str,
        best_bid: float | None,
        best_ask: float | None,
        tick_size: float | None = None,
        min_order_size: float | None = None,
    ) -> None:
        parts = [f"BOOK token={token_id}"]
        if best_bid is not None:
            parts.append(f"bid={best_bid}")
        if best_ask is not None:
            parts.append(f"ask={best_ask}")
        self._command(" ".join(parts))
        if tick_size is not None:
            self._command(f"TICK token={token_id} size={tick_size}")
        if min_order_size is not None:
            self._command(f"MINSIZE token={token_id} size={min_order_size}")

    def apply_market_event(self, event: dict[str, Any]) -> None:
        token_id = _event_token_id(event)
        if not token_id:
            return
        event_type = _event_type(event)
        if event_type in {"book", "best_bid_ask"}:
            best_bid = _as_float(event.get("best_bid"))
            best_ask = _as_float(event.get("best_ask"))
            if best_bid is None:
                best_bid = _best_price(event.get("bids"), side="bid")
            if best_ask is None:
                best_ask = _best_price(event.get("asks"), side="ask")
            self.update_book(
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                tick_size=_as_float(event.get("tick_size")) or _as_float(event.get("new_tick_size")),
                min_order_size=_as_float(event.get("min_order_size")),
            )
            return
        if event_type == "price_change":
            self.update_book(
                token_id=token_id,
                best_bid=_as_float(event.get("best_bid")),
                best_ask=_as_float(event.get("best_ask")),
            )
            if (price := _as_float(event.get("price"))) is not None:
                self._command(f"PRICE token={token_id} price={price}")
            return
        if event_type == "last_trade_price":
            price = _as_float(event.get("price"))
            if price is not None:
                self._command(f"PRICE token={token_id} price={price}")
            return
        if event_type == "tick_size_change":
            tick_size = _as_float(event.get("tick_size")) or _as_float(event.get("new_tick_size"))
            if tick_size is not None:
                self._command(f"TICK token={token_id} size={tick_size}")
            return
        if event_type == "market_resolved":
            self.resolve_market(
                token_id=token_id,
                winner_token_id=_as_str(event.get("winning_asset_id")) or _as_str(event.get("winner_asset_id")),
                outcome=_as_str(event.get("winning_outcome")) or _as_str(event.get("winner")),
            )

    def guard_order(
        self,
        *,
        order_id: str,
        token_id: str,
        market_id: str,
        side: str,
        price: float,
        shares: float,
        post_only: bool,
    ) -> dict[str, str]:
        return self._command(
            " ".join(
                [
                    "GUARD",
                    f"id={order_id}",
                    f"token={token_id}",
                    f"market={market_id}",
                    f"side={side}",
                    f"price={price}",
                    f"shares={shares}",
                    f"post_only={str(post_only).lower()}",
                ]
            )
        )

    def register_order(
        self,
        *,
        order_id: str,
        token_id: str,
        market_id: str,
        side: str,
        price: float,
        shares: float,
        post_only: bool,
        now_s: int | None = None,
    ) -> dict[str, str]:
        payload = self._command(
            " ".join(
                [
                    "ORDER",
                    f"id={order_id}",
                    f"token={token_id}",
                    f"market={market_id}",
                    f"side={side}",
                    f"price={price}",
                    f"shares={shares}",
                    f"post_only={str(post_only).lower()}",
                    f"now={now_s or int(time())}",
                ]
            )
        )
        self._save()
        return payload

    def apply_fill(
        self,
        *,
        order_id: str,
        filled: float | None = None,
        remaining: float | None = None,
        status: str = "FILLED",
        now_s: int | None = None,
    ) -> dict[str, str]:
        parts = ["FILL", f"id={order_id}", f"status={status}", f"now={now_s or int(time())}"]
        if filled is not None:
            parts.append(f"filled={filled}")
        if remaining is not None:
            parts.append(f"remaining={remaining}")
        payload = self._command(" ".join(parts))
        self._save()
        return payload

    def apply_trade(
        self,
        *,
        order_id: str,
        matched: float,
        status: str = "MATCHED",
        now_s: int | None = None,
    ) -> dict[str, str]:
        payload = self._command(
            " ".join(
                [
                    "TRADE",
                    f"id={order_id}",
                    f"matched={matched}",
                    f"status={status}",
                    f"now={now_s or int(time())}",
                ]
            )
        )
        self._save()
        return payload

    def stale_orders(self, *, now_s: int | None = None, max_age_s: int) -> list[str]:
        payload = self._command(f"STALE now={now_s or int(time())} max_age={max_age_s}")
        order_ids = payload.get("order_ids", "")
        if not order_ids:
            return []
        return [item for item in order_ids.split(",") if item]

    def resolve_market(self, *, token_id: str, winner_token_id: str | None = None, outcome: str | None = None) -> None:
        parts = ["RESOLVE", f"token={token_id}"]
        if winner_token_id is not None:
            parts.append(f"winner={winner_token_id}")
        if outcome is not None:
            parts.append(f"outcome={outcome}")
        self._command(" ".join(parts))
        self._save()

    def apply_user_event(self, event: dict[str, Any]) -> list[dict[str, str]]:
        updates: list[dict[str, str]] = []
        event_type = _event_type(event)
        now_s = _timestamp_to_epoch_seconds(event)
        if event_type == "trade":
            status = _as_str(event.get("status")) or "MATCHED"
            for maker_order in event.get("maker_orders") or []:
                if not isinstance(maker_order, dict):
                    continue
                order_id = _as_str(maker_order.get("order_id"))
                matched = _as_float(maker_order.get("matched_amount"))
                if order_id and matched is not None:
                    updates.append(self.apply_trade(order_id=order_id, matched=matched, status=status, now_s=now_s))
            taker_order_id = _as_str(event.get("taker_order_id"))
            size = _as_float(event.get("size"))
            if taker_order_id and size is not None:
                updates.append(self.apply_trade(order_id=taker_order_id, matched=size, status=status, now_s=now_s))
            return updates

        order_id = _as_str(event.get("order_id")) or _as_str(event.get("orderId")) or _as_str(event.get("id"))
        if not order_id:
            return updates
        status = _as_str(event.get("status")) or _as_str(event.get("state")) or _as_str(event.get("type")) or "OPEN"
        original_size = _as_float(event.get("original_size")) or _as_float(event.get("size")) or _as_float(event.get("originalSize"))
        size_matched = _as_float(event.get("size_matched")) or _as_float(event.get("filled_size")) or _as_float(event.get("sizeMatched"))
        remaining = _as_float(event.get("remaining_size")) or _as_float(event.get("remainingSize"))
        if original_size is not None and size_matched is not None:
            remaining = max(0.0, round(original_size - size_matched, 8))
        updates.append(
            self.apply_fill(
                order_id=order_id,
                filled=size_matched,
                remaining=remaining,
                status=status.upper(),
                now_s=now_s,
            )
        )
        return updates

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._command(f"SAVE path={self._state_path}")

    def _command(self, line: str) -> dict[str, str]:
        self.ensure_started()
        assert self._proc is not None
        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("rust hot path daemon stdio is unavailable")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        response = self._proc.stdout.readline().strip()
        if not response:
            stderr = ""
            if self._proc.stderr is not None:
                stderr = self._proc.stderr.read().strip()
            raise RuntimeError(f"rust hot path daemon returned no response: {stderr}")
        if response == "PONG":
            return {"message": "PONG"}
        if response.startswith("ERR "):
            raise ValueError(response[4:])
        return _parse_ok_response(response)


_SESSION: RustHotPathSession | None = None


def rust_session(cfg: AppConfig) -> RustHotPathSession:
    global _SESSION
    if _SESSION is None:
        _SESSION = RustHotPathSession(cfg)
    return _SESSION


def reset_rust_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.close()
    _SESSION = None


def _parse_ok_response(response: str) -> dict[str, str]:
    if not response.startswith("OK"):
        return {"message": response}
    out: dict[str, str] = {}
    for part in response.split()[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key] = value
    return out


def _as_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _event_token_id(event: dict[str, Any]) -> str | None:
    for key in ("asset_id", "assetId", "token_id", "tokenId"):
        if (value := _as_str(event.get(key))) is not None:
            return value
    return None


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("eventType") or event.get("type") or "unknown").lower()


def _timestamp_to_epoch_seconds(event: dict[str, Any]) -> int:
    for key in ("timestamp", "ts", "time", "last_update"):
        value = event.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        raw = str(value).strip()
        if raw.isdigit():
            return int(raw)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    return int(time())


def _best_price(raw_levels: object, *, side: str) -> float | None:
    if not isinstance(raw_levels, list):
        return None
    prices: list[float] = []
    for item in raw_levels:
        if isinstance(item, dict):
            price = _as_float(item.get("price"))
        elif isinstance(item, list) and item:
            price = _as_float(item[0])
        else:
            price = None
        if price is not None:
            prices.append(price)
    if not prices:
        return None
    return max(prices) if side == "bid" else min(prices)
