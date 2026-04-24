from __future__ import annotations

from dataclasses import asdict
import time

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import log_suppressed_exception, track_event
from stonks_cli.polymarket.client import utc_now_iso
from stonks_cli.polymarket.exits import exit_decision
from stonks_cli.polymarket.execution import ExecutionOrder, executor_for_config
from stonks_cli.polymarket.guards import (
    active_halt_reason,
    clear_error_counters,
    evaluate_trade_guards,
    load_guard_state,
    record_live_error,
    record_stream_error,
)
from stonks_cli.polymarket.journal import append_journal, read_journal
from stonks_cli.polymarket.models import MarketScan, RuntimeStatus
from stonks_cli.polymarket.paper import init_paper_account, load_paper_account
from stonks_cli.polymarket.risk import build_trade_proposal
from stonks_cli.polymarket.scanner import StructuralScanConfig, enrich_scans_with_wallet_signals, scan_markets
from stonks_cli.polymarket.storage import load_runtime_status, save_runtime_status
from stonks_cli.polymarket.stream import MarketStateCache
from stonks_cli.polymarket.wallets import load_wallet_market_signals


def runtime_status() -> RuntimeStatus:
    return load_runtime_status()


def _current_open_positions() -> int:
    try:
        return len(load_paper_account().positions)
    except Exception:
        return 0


def run_structural_scan_once(
    client,
    *,
    limit: int,
    cfg: StructuralScanConfig,
    paper: bool,
    market_cache: MarketStateCache | None = None,
) -> tuple[RuntimeStatus, list]:
    try:
        append_journal("scan_started", limit=limit, paper=paper)
        scans = scan_markets(client, limit=limit, cfg=cfg, include_filtered=False)
        if market_cache is not None:
            scans = _apply_market_cache(scans, market_cache)
        signals = load_wallet_market_signals()
        if signals:
            scans = enrich_scans_with_wallet_signals(scans, signals)
        status = RuntimeStatus(
            mode="polymarket",
            state="idle",
            paper=paper,
            last_scan_at=utc_now_iso(),
            last_scan_count=limit,
            last_pass_count=len(scans),
            open_positions=_current_open_positions(),
            last_actions=[],
            last_error=None,
        )
        save_runtime_status(status)
        track_event(
            "polymarket.runtime.scan_once",
            limit=limit,
            pass_count=len(scans),
            paper=paper,
        )
        append_journal("scan_completed", limit=limit, paper=paper, pass_count=len(scans))
        return status, scans
    except Exception as e:
        status = RuntimeStatus(
            mode="polymarket",
            state="error",
            paper=paper,
            last_scan_at=utc_now_iso(),
            last_scan_count=limit,
            last_pass_count=0,
            open_positions=_current_open_positions(),
            last_actions=[],
            last_error=str(e),
        )
        save_runtime_status(status)
        track_event(
            "polymarket.runtime.scan_once.failed",
            level=40,
            limit=limit,
            paper=paper,
            error=str(e),
        )
        append_journal("scan_failed", limit=limit, paper=paper, error=str(e))
        raise


def maybe_auto_trade(cfg: AppConfig, scans: list) -> list[dict[str, object]]:
    if not cfg.polymarket.auto_trade_enabled:
        return []
    actions: list[dict[str, object]] = []
    executor = executor_for_config(cfg)
    try:
        account = load_paper_account()
    except Exception:
        if cfg.polymarket.paper:
            account = init_paper_account(cfg.polymarket.paper_starting_cash)
        else:
            return []

    for scan in scans:
        decision = build_trade_proposal(cfg, account, scan)
        if not decision.accepted or decision.proposal is None:
            append_journal(
                "proposal_rejected",
                token_id=scan.token_id,
                market_id=scan.market_id,
                slug=scan.slug,
                reasons=decision.reasons,
                score=scan.score,
            )
            continue
        guard_reasons = evaluate_trade_guards(cfg, account, decision.proposal)
        if guard_reasons:
            append_journal(
                "proposal_rejected",
                token_id=decision.proposal.token_id,
                market_id=decision.proposal.market_id,
                slug=decision.proposal.slug,
                reasons=guard_reasons,
                score=decision.proposal.score,
            )
            continue
        try:
            result = executor.execute(
                ExecutionOrder(
                    token_id=decision.proposal.token_id,
                    market_id=decision.proposal.market_id,
                    slug=decision.proposal.slug,
                    outcome=decision.proposal.outcome,
                    side=decision.proposal.side,
                    price=decision.proposal.price,
                    shares=decision.proposal.shares,
                    target_price=decision.proposal.target_price,
                    stop_price=decision.proposal.stop_price,
                    reason=decision.proposal.reason,
                )
            )
        except Exception as e:
            log_suppressed_exception(context="polymarket.runtime.auto_trade", error=e, token_id=decision.proposal.token_id)
            append_journal(
                "auto_trade_error",
                token_id=decision.proposal.token_id,
                market_id=decision.proposal.market_id,
                slug=decision.proposal.slug,
                error=str(e),
            )
            if not cfg.polymarket.paper:
                record_live_error(cfg, reason=type(e).__name__)
            break
        actions.append(result)
        break
    return actions


def maybe_auto_exit(cfg: AppConfig, scans: list) -> list[dict[str, object]]:
    if not cfg.polymarket.auto_exit_enabled:
        return []
    try:
        account = load_paper_account()
    except Exception:
        return []
    if not account.positions:
        return []

    prices = {scan.token_id: scan.midpoint for scan in scans if scan.token_id is not None and scan.midpoint is not None}
    executor = executor_for_config(cfg)
    actions: list[dict[str, object]] = []
    for position in account.positions:
        current_price = prices.get(position.token_id)
        decision = exit_decision(cfg, position, current_price=current_price)
        if not decision.should_exit or current_price is None:
            continue
        result = executor.execute(
            ExecutionOrder(
                token_id=position.token_id,
                market_id=position.market_id,
                slug=position.slug,
                outcome=position.outcome,
                side="SELL",
                price=current_price,
                shares=position.shares,
                reason=decision.reason,
            )
        )
        append_journal(
            "auto_exit",
            token_id=position.token_id,
            market_id=position.market_id,
            slug=position.slug,
            reason=decision.reason,
            price=current_price,
            shares=position.shares,
        )
        actions.append(result)
    return actions


def maybe_reconcile_live_orders(cfg: AppConfig) -> list[dict[str, object]]:
    if cfg.polymarket.paper:
        return []
    executor = executor_for_config(cfg)
    cancel_stale = getattr(executor, "cancel_stale_orders", None)
    if cancel_stale is None:
        return []
    try:
        actions = cancel_stale()
    except Exception as e:
        log_suppressed_exception(context="polymarket.runtime.reconcile_live_orders", error=e)
        append_journal("live_reconcile_error", error=str(e))
        record_live_error(cfg, reason=type(e).__name__)
        return []
    if actions:
        clear_error_counters()
    return actions


def run_runtime_cycle(
    client,
    *,
    cfg: AppConfig,
    limit: int,
    scan_cfg: StructuralScanConfig,
    market_cache: MarketStateCache | None = None,
) -> dict[str, object]:
    status, scans = run_structural_scan_once(
        client,
        limit=limit,
        cfg=scan_cfg,
        paper=cfg.polymarket.paper,
        market_cache=market_cache,
    )
    try:
        account = load_paper_account()
        missing_tokens = [position.token_id for position in account.positions if position.token_id not in {scan.token_id for scan in scans}]
        for token_id in missing_tokens:
            midpoint = None
            if market_cache is not None:
                snapshot = market_cache.get(token_id)
                if snapshot is not None:
                    midpoint = snapshot.midpoint or snapshot.last_trade_price
            if midpoint is None:
                midpoint = client.get_midpoint(token_id)
            if midpoint is None:
                continue
            scans.append(
                MarketScan(
                    market_id="",
                    slug=None,
                    question="",
                    token_id=token_id,
                    outcome=None,
                    midpoint=midpoint,
                    bids_depth_usd=0.0,
                    asks_depth_usd=0.0,
                    liquidity_usd=None,
                    volume_usd=None,
                    hours_to_resolution=None,
                    complement_deviation_bps=None,
                    score=0.0,
                    status="PASS",
                    reasons=["position_mark_refresh"],
                    target_wallet_count=0,
                    target_trade_count=0,
                    target_net_volume=0.0,
                )
            )
    except Exception:
        pass
    reconcile_actions = maybe_reconcile_live_orders(cfg)
    exit_actions = maybe_auto_exit(cfg, scans)
    trade_actions = maybe_auto_trade(cfg, scans)
    actions = reconcile_actions + exit_actions + trade_actions
    updated = RuntimeStatus(
        mode=status.mode,
        state="idle" if not actions else "traded",
        paper=status.paper,
        last_scan_at=status.last_scan_at,
        last_scan_count=status.last_scan_count,
        last_pass_count=status.last_pass_count,
        open_positions=_current_open_positions(),
        last_actions=[f"{action.get('action')}:{action.get('token_id')}" for action in actions],
        last_error=None,
    )
    save_runtime_status(updated)
    append_journal(
        "runtime_cycle_completed",
        state=updated.state,
        open_positions=updated.open_positions,
        action_count=len(actions),
    )
    return {
        "status": asdict(updated),
        "queue": [asdict(scan) for scan in scans],
        "actions": actions,
        "journal": read_journal(limit=20),
    }


def run_runtime_loop(
    client,
    *,
    cfg: AppConfig,
    limit: int,
    scan_cfg: StructuralScanConfig,
    cycles: int,
    sleep_seconds: float | None = None,
    stream_hook=None,
) -> dict[str, object]:
    if cycles <= 0:
        raise ValueError("cycles must be positive")
    market_cache = MarketStateCache()
    results: list[dict[str, object]] = []
    sleep_for = cfg.polymarket.loop_interval_ms / 1000.0 if sleep_seconds is None else sleep_seconds
    for iteration in range(1, cycles + 1):
        halt_reason = active_halt_reason(load_guard_state())
        if halt_reason:
            append_journal("runtime_loop_halted", iteration=iteration, reason=halt_reason)
            break
        if stream_hook is not None:
            try:
                stream_hook(iteration=iteration, market_cache=market_cache)
                clear_error_counters()
            except Exception as e:
                log_suppressed_exception(context="polymarket.runtime.loop.stream_hook", error=e, iteration=iteration)
                state = record_stream_error(cfg, reason=type(e).__name__)
                append_journal(
                    "runtime_loop_stream_error",
                    iteration=iteration,
                    error=str(e),
                    stream_error_count=state.stream_error_count,
                    halted=state.halted,
                )
                if state.halted:
                    break
        try:
            result = run_runtime_cycle(client, cfg=cfg, limit=limit, scan_cfg=scan_cfg, market_cache=market_cache)
        except Exception as e:
            log_suppressed_exception(context="polymarket.runtime.loop.cycle", error=e, iteration=iteration)
            state = record_live_error(cfg, reason=type(e).__name__)
            append_journal(
                "runtime_loop_cycle_error",
                iteration=iteration,
                error=str(e),
                live_error_count=state.live_error_count,
                halted=state.halted,
            )
            if state.halted:
                break
            continue
        results.append(result)
        append_journal(
            "runtime_loop_iteration",
            iteration=iteration,
            state=result["status"].get("state"),
            action_count=len(result["actions"]),
        )
        if iteration < cycles and sleep_for > 0:
            time.sleep(sleep_for)
    final_status = results[-1]["status"] if results else asdict(runtime_status())
    return {
        "cycles": cycles,
        "sleep_seconds": sleep_for,
        "final_status": final_status,
        "guard_state": asdict(load_guard_state()),
        "iterations": [
            {
                "iteration": idx + 1,
                "status": result["status"],
                "action_count": len(result["actions"]),
            }
            for idx, result in enumerate(results)
        ],
    }


def _apply_market_cache(scans: list[MarketScan], market_cache: MarketStateCache) -> list[MarketScan]:
    updated: list[MarketScan] = []
    for scan in scans:
        if scan.token_id is None:
            updated.append(scan)
            continue
        snapshot = market_cache.get(scan.token_id)
        if snapshot is None:
            updated.append(scan)
            continue
        midpoint = snapshot.midpoint or snapshot.last_trade_price or scan.midpoint
        reasons = list(scan.reasons)
        if midpoint is not None and midpoint != scan.midpoint:
            reasons.append("stream_midpoint")
        updated.append(
            MarketScan(
                market_id=scan.market_id,
                slug=scan.slug,
                question=scan.question,
                token_id=scan.token_id,
                outcome=scan.outcome,
                midpoint=midpoint,
                bids_depth_usd=scan.bids_depth_usd,
                asks_depth_usd=scan.asks_depth_usd,
                liquidity_usd=scan.liquidity_usd,
                volume_usd=scan.volume_usd,
                hours_to_resolution=scan.hours_to_resolution,
                complement_deviation_bps=scan.complement_deviation_bps,
                score=scan.score,
                status=scan.status,
                reasons=reasons,
                target_wallet_count=scan.target_wallet_count,
                target_trade_count=scan.target_trade_count,
                target_net_volume=scan.target_net_volume,
            )
        )
    return updated
