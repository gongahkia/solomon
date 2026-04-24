from __future__ import annotations

from dataclasses import asdict

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import track_event
from stonks_cli.polymarket.client import utc_now_iso
from stonks_cli.polymarket.execution import ExecutionOrder, executor_for_config
from stonks_cli.polymarket.models import RuntimeStatus
from stonks_cli.polymarket.paper import init_paper_account, load_paper_account
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
        raise


def maybe_auto_trade(cfg: AppConfig, scans: list) -> list[dict[str, object]]:
    if not cfg.polymarket.auto_trade_enabled:
        return []
    actions: list[dict[str, object]] = []
    executor = executor_for_config(cfg)
    try:
        account = load_paper_account()
        existing = {position.token_id: position for position in account.positions}
        cash = account.cash
    except Exception:
        if cfg.polymarket.paper:
            account = init_paper_account(cfg.polymarket.paper_starting_cash)
            existing = {position.token_id: position for position in account.positions}
            cash = account.cash
        else:
            existing = {}
            cash = 0.0
    if cash <= 0:
        existing = {}
        cash = cfg.polymarket.paper_starting_cash

    max_notional = cash * cfg.polymarket.max_position_fraction
    for scan in scans:
        if scan.status != "PASS":
            continue
        if scan.token_id is None or scan.midpoint is None or scan.midpoint <= 0:
            continue
        if scan.score < cfg.polymarket.auto_trade_min_score:
            continue
        if scan.target_wallet_count < cfg.polymarket.auto_trade_min_target_wallets:
            continue
        if scan.token_id in existing:
            continue
        shares = round(max_notional / scan.midpoint, 6)
        if shares <= 0:
            continue
        result = executor.execute(
            ExecutionOrder(
                token_id=scan.token_id,
                market_id=scan.market_id,
                slug=scan.slug,
                outcome=scan.outcome,
                side="BUY",
                price=scan.midpoint,
                shares=shares,
            )
        )
        actions.append(result)
        break
    return actions


def run_runtime_cycle(client, *, cfg: AppConfig, limit: int, scan_cfg: StructuralScanConfig) -> dict[str, object]:
    status, scans = run_structural_scan_once(client, limit=limit, cfg=scan_cfg, paper=cfg.polymarket.paper)
    actions = maybe_auto_trade(cfg, scans)
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
    return {
        "status": asdict(updated),
        "queue": [asdict(scan) for scan in scans],
        "actions": actions,
    }
