from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir
from stonks_cli.polymarket.lifecycle import load_live_orders
from stonks_cli.polymarket.models import PaperAccount, TradeProposal


@dataclass(frozen=True)
class GuardState:
    trading_day: str
    halted: bool = False
    halt_reason: str | None = None
    live_error_count: int = 0
    stream_error_count: int = 0


def guard_state_path() -> Path:
    return default_state_dir() / "polymarket_guard.json"


def manual_halt_path() -> Path:
    return default_state_dir() / "polymarket.halt"


def load_guard_state() -> GuardState:
    path = guard_state_path()
    if not path.exists():
        return GuardState(trading_day=_today_utc())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_suppressed_exception(context="polymarket.guards.load", error=e, path=path)
        return GuardState(trading_day=_today_utc(), halted=True, halt_reason="guard_state_corrupt")
    state = GuardState(
        trading_day=str(payload.get("trading_day") or _today_utc()),
        halted=bool(payload.get("halted", False)),
        halt_reason=payload.get("halt_reason"),
        live_error_count=int(payload.get("live_error_count") or 0),
        stream_error_count=int(payload.get("stream_error_count") or 0),
    )
    return _roll_day(state)


def save_guard_state(state: GuardState) -> None:
    path = guard_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def halt_trading(*, reason: str) -> GuardState:
    state = replace_state(load_guard_state(), halted=True, halt_reason=reason)
    save_guard_state(state)
    path = manual_halt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason.strip() or "manual_halt", encoding="utf-8")
    return state


def resume_trading() -> GuardState:
    path = manual_halt_path()
    if path.exists():
        path.unlink()
    state = replace_state(load_guard_state(), halted=False, halt_reason=None, live_error_count=0, stream_error_count=0)
    save_guard_state(state)
    return state


def active_halt_reason(state: GuardState | None = None) -> str | None:
    path = manual_halt_path()
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip() or "manual_halt"
        except Exception:
            return "manual_halt"
    use_state = load_guard_state() if state is None else state
    return use_state.halt_reason if use_state.halted else None


def evaluate_trade_guards(cfg: AppConfig, account: PaperAccount, proposal: TradeProposal) -> list[str]:
    state = load_guard_state()
    reasons: list[str] = []
    halt_reason = active_halt_reason(state)
    if halt_reason:
        reasons.append(f"halted:{halt_reason}")
    if not cfg.polymarket.paper and cfg.polymarket.live_require_armed_env and not live_trading_armed(cfg):
        reasons.append("live_trading_not_armed")
    if cfg.polymarket.max_daily_loss > 0 and account.realized_pnl <= -cfg.polymarket.max_daily_loss:
        reasons.append("max_daily_loss_reached")
    if cfg.polymarket.max_market_notional > 0:
        market_notional = sum(
            position.shares * position.avg_price for position in account.positions if position.market_id == proposal.market_id
        )
        if market_notional + proposal.notional > cfg.polymarket.max_market_notional:
            reasons.append("max_market_notional_reached")
    if not cfg.polymarket.paper and _open_live_order_count() >= cfg.polymarket.max_live_open_orders:
        reasons.append("max_live_open_orders_reached")
    return reasons


def record_live_error(cfg: AppConfig, *, reason: str) -> GuardState:
    state = load_guard_state()
    live_errors = state.live_error_count + 1
    halted = state.halted or live_errors >= cfg.polymarket.max_consecutive_live_errors
    halt_reason = state.halt_reason
    if halted and halt_reason is None:
        halt_reason = f"live_errors:{reason}"
    updated = replace_state(state, halted=halted, halt_reason=halt_reason, live_error_count=live_errors)
    save_guard_state(updated)
    return updated


def record_stream_error(cfg: AppConfig, *, reason: str) -> GuardState:
    state = load_guard_state()
    stream_errors = state.stream_error_count + 1
    halted = state.halted or stream_errors >= cfg.polymarket.max_consecutive_stream_errors
    halt_reason = state.halt_reason
    if halted and halt_reason is None:
        halt_reason = f"stream_errors:{reason}"
    updated = replace_state(state, halted=halted, halt_reason=halt_reason, stream_error_count=stream_errors)
    save_guard_state(updated)
    return updated


def clear_error_counters() -> GuardState:
    state = replace_state(load_guard_state(), live_error_count=0, stream_error_count=0)
    save_guard_state(state)
    return state


def live_trading_armed(cfg: AppConfig) -> bool:
    raw = os.getenv(cfg.polymarket.live_armed_env or "STONKS_CLI_POLYMARKET_LIVE_ARMED", "").strip().lower()
    return raw in {"1", "true", "yes", "armed"}


def replace_state(state: GuardState, **updates) -> GuardState:
    return GuardState(
        trading_day=str(updates.get("trading_day", state.trading_day)),
        halted=bool(updates.get("halted", state.halted)),
        halt_reason=updates.get("halt_reason", state.halt_reason),
        live_error_count=int(updates.get("live_error_count", state.live_error_count)),
        stream_error_count=int(updates.get("stream_error_count", state.stream_error_count)),
    )


def _open_live_order_count() -> int:
    return sum(1 for record in load_live_orders() if record.status in {"OPEN", "PLACEMENT", "UPDATE", "LIVE", "PARTIAL"})


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def _roll_day(state: GuardState) -> GuardState:
    today = _today_utc()
    if state.trading_day == today:
        return state
    rolled = GuardState(trading_day=today, halted=state.halted, halt_reason=state.halt_reason)
    save_guard_state(rolled)
    return rolled
