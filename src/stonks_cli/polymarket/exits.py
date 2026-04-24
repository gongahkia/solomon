from __future__ import annotations

from datetime import UTC, datetime

from stonks_cli.config import AppConfig
from stonks_cli.polymarket.models import ExitDecision, PaperPosition


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def exit_decision(
    cfg: AppConfig,
    position: PaperPosition,
    *,
    current_price: float | None,
    now: datetime | None = None,
) -> ExitDecision:
    if not cfg.polymarket.auto_exit_enabled:
        return ExitDecision(should_exit=False)
    if current_price is None:
        opened = _parse_ts(position.opened_at)
        if opened is None:
            return ExitDecision(should_exit=False)
        now_dt = now or datetime.now(UTC)
        hours_open = (now_dt - opened).total_seconds() / 3600.0
        if hours_open >= cfg.polymarket.stale_position_hours:
            return ExitDecision(should_exit=True, reason="STALE_POSITION")
        return ExitDecision(should_exit=False)

    if position.target_price is not None and current_price >= position.target_price:
        return ExitDecision(should_exit=True, reason="TARGET_HIT")
    if position.stop_price is not None and current_price <= position.stop_price:
        return ExitDecision(should_exit=True, reason="STOP_LOSS")

    opened = _parse_ts(position.opened_at)
    if opened is not None:
        now_dt = now or datetime.now(UTC)
        hours_open = (now_dt - opened).total_seconds() / 3600.0
        if hours_open >= cfg.polymarket.stale_position_hours:
            return ExitDecision(should_exit=True, reason="STALE_POSITION")

    return ExitDecision(should_exit=False)
