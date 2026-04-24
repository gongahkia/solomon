from __future__ import annotations

from dataclasses import asdict

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import track_event
from stonks_cli.polymarket.client import utc_now_iso
from stonks_cli.polymarket.exits import exit_decision
from stonks_cli.polymarket.execution import ExecutionOrder, executor_for_config
from stonks_cli.polymarket.journal import append_journal, read_journal
from stonks_cli.polymarket.models import RuntimeStatus
from stonks_cli.polymarket.paper import init_paper_account, load_paper_account
from stonks_cli.polymarket.risk import build_trade_proposal
from stonks_cli.polymarket.scanner import StructuralScanConfig, enrich_scans_with_wallet_signals, scan_markets
from stonks_cli.polymarket.storage import load_runtime_status, save_runtime_status
from stonks_cli.polymarket.wallets import load_wallet_market_signals


def runtime_status() -> RuntimeStatus:
    return load_runtime_status()


def _current_open_positions() -> int:
    try:
        return len(load_paper_account().positions)
    except Exception:
        return 0


def run_structural_scan_once(client, *, limit: int, cfg: StructuralScanConfig, paper: bool) -> tuple[RuntimeStatus, list]:
    try:
        append_journal("scan_started", limit=limit, paper=paper)
        scans = scan_markets(client, limit=limit, cfg=cfg, include_filtered=False)
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


def run_runtime_cycle(client, *, cfg: AppConfig, limit: int, scan_cfg: StructuralScanConfig) -> dict[str, object]:
    status, scans = run_structural_scan_once(client, limit=limit, cfg=scan_cfg, paper=cfg.polymarket.paper)
    exit_actions = maybe_auto_exit(cfg, scans)
    trade_actions = maybe_auto_trade(cfg, scans)
    actions = exit_actions + trade_actions
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
