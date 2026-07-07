from __future__ import annotations

import os
from collections.abc import Mapping

from stonks_cli.whalemirror.models import (
    SG_BLOCKED_EXECUTION_VENUES,
    SG_BLOCKED_STRATEGY_CLASSES,
    MirrorMode,
    Venue,
    coerce_venue,
)

TRUTHY_ARM_VALUES = frozenset({"1", "true", "yes", "armed"})
LIVE_ARM_ENV_BY_VENUE = {
    Venue.HYPERLIQUID: "STONKS_CLI_HYPERLIQUID_LIVE_ARMED",
}


def live_arm_env(venue: Venue | str) -> str:
    resolved = coerce_venue(venue)
    if resolved in LIVE_ARM_ENV_BY_VENUE:
        return LIVE_ARM_ENV_BY_VENUE[resolved]
    return f"STONKS_CLI_{str(resolved).upper()}_LIVE_ARMED"


def live_execution_armed(venue: Venue | str, env: Mapping[str, str] | None = None) -> bool:
    use_env = os.environ if env is None else env
    raw = use_env.get(live_arm_env(venue), "").strip().lower()
    return raw in TRUTHY_ARM_VALUES


def evaluate_execution_guards(
    *,
    venue: Venue | str,
    mode: MirrorMode | str,
    sg_resident: bool = True,
    require_arm: bool = True,
    heartbeat_ok: bool | None = None,
    emergency_stop_active: bool = False,
    consensus_approved: bool | None = None,
    strategy_class: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    resolved_venue = coerce_venue(venue)
    resolved_mode = MirrorMode(mode)
    reasons: list[str] = []

    if resolved_mode is not MirrorMode.LIVE:
        return reasons

    if sg_resident and resolved_venue in SG_BLOCKED_EXECUTION_VENUES:
        reasons.append(f"venue_blocked_for_sg:{resolved_venue}")

    normalized_strategy = (strategy_class or "").strip().lower().replace("-", "_")
    if sg_resident and normalized_strategy in SG_BLOCKED_STRATEGY_CLASSES:
        reasons.append(f"strategy_blocked_for_sg:{normalized_strategy}")

    if require_arm and not live_execution_armed(resolved_venue, env=env):
        reasons.append(f"live_trading_not_armed:{live_arm_env(resolved_venue)}")

    if heartbeat_ok is False:
        reasons.append("heartbeat_not_fresh")

    if emergency_stop_active:
        reasons.append("emergency_stop_active")

    if consensus_approved is False:
        reasons.append("consensus_not_approved")

    return reasons
