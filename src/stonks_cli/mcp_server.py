from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from typer.testing import CliRunner

from stonks_cli.carry.carry_health import build_carry_health_report
from stonks_cli.carry.carry_live import CarryLivePreflightEvidence, evaluate_carry_live_preflight
from stonks_cli.carry.carry_paper import PaperCarryConfig, run_paper_carry_for_duration, write_paper_carry_artifacts
from stonks_cli.carry.carry_scanner import CarryCostAssumptions, load_carry_inputs_fixture, scan_hyperliquid_carry
from stonks_cli.cli import (
    _load_daily_report_inputs,
    _load_portfolio_snapshot,
    _load_score_components,
    _portfolio_snapshot_to_data,
)
from stonks_cli.cli import (
    app as cli_app,
)
from stonks_cli.cli_experience import inspect_home, removable_paths, remove_managed_paths
from stonks_cli.commands import do_config_validate, do_doctor, do_smoke_doctor
from stonks_cli.config import config_path, load_config, redacted_config_data, save_config
from stonks_cli.paths import default_cache_dir, default_state_dir
from stonks_cli.research.attribution import DEFAULT_ATTRIBUTION_FIXTURE, rank_wallets_from_fixture
from stonks_cli.research.hyperliquid import HyperliquidOrderClient
from stonks_cli.research.ingestion import DEFAULT_CAPTURE_FIXTURE, replay_capture_fixture, write_capture_jsonl
from stonks_cli.research.ledger import DEFAULT_REPLAY_FIXTURE, write_fixture_artifacts
from stonks_cli.research.paper_analysis import (
    DEFAULT_PAPER_MIRROR_FIXTURE,
    PaperAnalysisConfig,
    replay_paper_analysis_fixture,
)
from stonks_cli.research.validation_gates import (
    assess_gate,
    gate_state_path,
    load_gate_state,
    record_capture_probe,
    write_gate_report,
)
from stonks_cli.vnext.account_import import import_moomoo_accounts
from stonks_cli.vnext.broker_app_order_ticket import render_broker_app_order_ticket
from stonks_cli.vnext.crypto_universe_snapshot import load_crypto_universe_snapshot
from stonks_cli.vnext.holdings_import import import_moomoo_holdings
from stonks_cli.vnext.market_data_refresh import refresh_moomoo_market_data
from stonks_cli.vnext.moomoo import MoomooAccount
from stonks_cli.vnext.portfolio_risk_report import render_portfolio_risk_report
from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket
from stonks_cli.vnext.weighted_ranker import rank_weighted_assets

SERVER_NAME = "stonks-cli"
CONFIRMATION_TTL_SECONDS = 300
_SAFE_CONFIG_FIELDS = {
    "carry.alert_events",
    "carry.alert_sink",
    "carry.min_net_apr",
    "vnext.moomoo.account_id",
    "vnext.moomoo.enabled",
    "vnext.moomoo.host",
    "vnext.moomoo.port",
    "vnext.operator.telegram.enabled",
    "vnext.research.cadence",
    "vnext.research.enabled",
}
_READONLY_CLI_COMMANDS = {
    "doctor",
    "health-carry",
    "home",
    "import-account",
    "preflight-carry-live",
    "rank",
    "rank-wallet",
    "refresh-market",
    "refresh-market-data",
    "replay-paper",
    "report-daily",
    "scan-carry",
    "show-config",
    "show-portfolio",
    "status-gate",
    "ticket-order",
    "universe-crypto",
    "validate-config",
    "version",
    "where-config",
}
_CLI_PATH_FLAGS = {
    "--capture-dir",
    "--components",
    "--fixture",
    "--health",
    "--input",
    "--ledger",
    "--normalized",
    "--raw",
    "--reconciliation",
    "--snapshot",
    "--state-dir",
    "--stream-heartbeat",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _state_root() -> Path:
    root = default_state_dir() / "mcp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _confirmations_path() -> Path:
    return _state_root() / "confirmations.json"


def _jobs_root() -> Path:
    root = _state_root() / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _allowed_roots() -> tuple[Path, ...]:
    roots = {config_path().expanduser().resolve().parent, default_state_dir().resolve(), default_cache_dir().resolve()}
    configured = os.getenv("STONKS_CLI_MCP_ROOTS", "")
    for raw in configured.split(os.pathsep):
        if raw.strip():
            roots.add(Path(raw).expanduser().resolve())
    return tuple(sorted(roots))


def _checked_path(value: str | Path, *, write: bool = False) -> Path:
    path = Path(value).expanduser()
    resolved = path.resolve(strict=False)
    if not resolved.is_absolute() or not any(resolved.is_relative_to(root) for root in _allowed_roots()):
        raise ValueError("path is outside STONKS_CLI_MCP_ROOTS or managed app directories")
    if not write and (not resolved.exists() or resolved.is_symlink()):
        raise ValueError("path must be an existing regular path")
    if write and any(parent.is_symlink() for parent in (resolved, *resolved.parents) if parent.exists()):
        raise ValueError("refusing a path with symlinked parents")
    return resolved


def _validate_readonly_cli_args(command: str, args: list[str]) -> None:
    if command not in _READONLY_CLI_COMMANDS:
        raise ValueError("command is not available through the read-only MCP bridge")
    for index, argument in enumerate(args[:-1]):
        if argument in _CLI_PATH_FLAGS:
            _checked_path(args[index + 1])
    if any(argument in {"--out", "--report", "--tearsheet", "--no-paper"} for argument in args):
        raise ValueError("write and live-mode CLI options are unavailable through the MCP bridge")


def _read_confirmations() -> dict[str, dict[str, Any]]:
    data = _load_json(_confirmations_path(), {})
    now = _now()
    active = {
        key: value for key, value in data.items() if datetime.fromisoformat(value["expires_at"]).astimezone(UTC) > now
    }
    if active != data:
        _atomic_json(_confirmations_path(), active)
    return active


def _prepare(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    confirmations = _read_confirmations()
    confirmation_id = secrets.token_urlsafe(24)
    confirmations[confirmation_id] = {
        "kind": kind,
        "params": params,
        "expires_at": (_now() + timedelta(seconds=CONFIRMATION_TTL_SECONDS)).isoformat(),
    }
    _atomic_json(_confirmations_path(), confirmations)
    return {
        "confirmation_id": confirmation_id,
        "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
        "kind": kind,
        "preview": _preview(kind, params),
    }


def _confirm(confirmation_id: str) -> dict[str, Any]:
    confirmations = _read_confirmations()
    item = confirmations.pop(confirmation_id, None)
    if item is None:
        raise ValueError("unknown or expired confirmation_id")
    _atomic_json(_confirmations_path(), confirmations)
    return _execute_mutation(str(item["kind"]), dict(item["params"]))


def _preview(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind in {"clean", "uninstall"}:
        return {"paths": [str(path) for path in removable_paths(include_config=kind == "uninstall")]}
    if kind == "config_onboard":
        return {"config_path": str(config_path()), "live_execution": "blocked", **params}
    if kind == "config_update":
        return {"config_path": str(config_path()), "fields": sorted(params["updates"]), "live_execution": "blocked"}
    if kind in {"fixture_ledger", "fixture_ingest", "fixture_capture_gate"}:
        return params
    if kind in {"carry_paper_job", "ingest_job", "cancel_job"}:
        return params
    raise ValueError("unsupported mutation kind")


def _apply_safe_updates(updates: dict[str, Any]) -> dict[str, Any]:
    if not updates or set(updates) - _SAFE_CONFIG_FIELDS:
        raise ValueError("only documented safe configuration fields may be changed through MCP")
    cfg = load_config()
    payload = cfg.model_dump(mode="json")
    for field, value in updates.items():
        current = payload
        parts = field.split(".")
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = value
    payload["carry"]["paper"] = True
    payload["carry"]["live_armed"] = False
    payload["vnext"]["features"]["execution"] = False
    payload["vnext"]["features"]["broker_data"] = bool(payload["vnext"]["moomoo"]["enabled"])
    payload["vnext"]["features"]["crypto_research"] = bool(payload["vnext"]["research"]["enabled"])
    payload["vnext"]["features"]["operator_reports"] = bool(payload["vnext"]["operator"]["telegram"]["enabled"])
    payload["vnext"]["enabled"] = any(
        payload["vnext"]["features"][key] for key in ("broker_data", "crypto_research", "operator_reports")
    )
    updated = type(cfg).model_validate(payload)
    save_config(updated)
    return {"config": redacted_config_data(updated), "live_execution": "blocked"}


def _execute_mutation(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind == "config_onboard":
        return _apply_safe_updates(
            {
                "vnext.research.enabled": bool(params.get("research_enabled", False)),
                "vnext.moomoo.enabled": bool(params.get("moomoo_enabled", False)),
                "vnext.operator.telegram.enabled": bool(params.get("reports_enabled", False)),
                "carry.alert_sink": params.get("alert_sink", "disabled"),
            }
        )
    if kind == "config_update":
        return _apply_safe_updates(dict(params["updates"]))
    if kind == "clean":
        return {"removed": [str(path) for path in remove_managed_paths(removable_paths(include_config=False))]}
    if kind == "uninstall":
        return {
            "removed": [str(path) for path in remove_managed_paths(removable_paths(include_config=True))],
            "package_removal": "Use your installer, for example: uv tool uninstall stonks-cli",
        }
    if kind == "fixture_ledger":
        fixture = _checked_path(params.get("fixture", str(DEFAULT_REPLAY_FIXTURE)))
        ledger = _checked_path(params["ledger"], write=True)
        tearsheet = _checked_path(params["tearsheet"], write=True)
        return write_fixture_artifacts(fixture_path=fixture, ledger_path=ledger, tearsheet_path=tearsheet)
    if kind == "fixture_ingest":
        fixture = _checked_path(params.get("fixture", str(DEFAULT_CAPTURE_FIXTURE)))
        out = _checked_path(params["out"], write=True)
        trades, health = replay_capture_fixture(fixture)
        write_capture_jsonl(trades, out)
        return {"out_path": str(out), "health": health.to_dict(), "trade_count": len(trades)}
    if kind == "fixture_capture_gate":
        fixture = _checked_path(params.get("fixture", str(DEFAULT_CAPTURE_FIXTURE)))
        state_dir = _checked_path(params["state_dir"], write=True)
        capture_out_dir = _checked_path(params["capture_out_dir"], write=True)
        report = _checked_path(params["report"], write=True)
        state = record_capture_probe(
            state_dir=state_dir,
            fixture_path=fixture,
            capture_out_dir=capture_out_dir,
            reset=bool(params.get("reset", False)),
        )
        write_gate_report(state, report_path=report)
        return {
            "state_path": str(gate_state_path(state_dir=state_dir)),
            "report_path": str(report),
            "assessment": assess_gate(state).to_dict(),
        }
    if kind in {"carry_paper_job", "ingest_job"}:
        return _start_job(kind, params)
    if kind == "cancel_job":
        return _cancel_job(str(params["job_id"]))
    raise ValueError("unsupported mutation kind")


def _job_path(job_id: str) -> Path:
    if not job_id.isalnum() or len(job_id) != 32:
        raise ValueError("invalid job_id")
    return _jobs_root() / f"{job_id}.json"


def _start_job(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid4().hex
    path = _job_path(job_id)
    log_path = _jobs_root() / f"{job_id}.log"
    record = {
        "job_id": job_id,
        "kind": kind,
        "status": "starting",
        "created_at": _now().isoformat(),
        "params": params,
        "log_path": str(log_path),
    }
    _atomic_json(path, record)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "stonks_cli.mcp_server", "--worker", job_id],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    record["pid"] = process.pid
    record["status"] = "running"
    _atomic_json(path, record)
    return {"job_id": job_id, "status": "running", "log_path": str(log_path)}


def _job_record(job_id: str) -> dict[str, Any]:
    return dict(_load_json(_job_path(job_id), {}))


def _cancel_job(job_id: str) -> dict[str, Any]:
    record = _job_record(job_id)
    if not record:
        raise ValueError("unknown job_id")
    if record.get("status") not in {"starting", "running"}:
        return {"job_id": job_id, "status": record.get("status")}
    pid = int(record.get("pid", 0))
    if pid > 0:
        os.killpg(pid, signal.SIGTERM)
    record["status"] = "cancel_requested"
    record["updated_at"] = _now().isoformat()
    _atomic_json(_job_path(job_id), record)
    return {"job_id": job_id, "status": "cancel_requested"}


def _run_worker(job_id: str) -> None:
    record = _job_record(job_id)
    if not record:
        raise ValueError("unknown job")
    try:
        kind = record["kind"]
        params = dict(record["params"])
        if kind == "carry_paper_job":
            fixture = _checked_path(params["fixture"]) if params.get("fixture") else None
            state_dir = _checked_path(params["state_dir"], write=True)
            report = _checked_path(params["report"], write=True)
            ledger = _checked_path(params["ledger"], write=True)
            cfg = load_config()
            fetch = (
                (lambda: load_carry_inputs_fixture(fixture))
                if fixture
                else (
                    lambda: HyperliquidOrderClient().fetch_carry_inputs(tuple(params.get("assets") or ("BTC", "ETH")))
                )
            )
            paths: dict[str, str] = {}

            def persist(result: Any) -> None:
                nonlocal paths
                paths = write_paper_carry_artifacts(
                    result=result, state_dir=state_dir, report_path=report, ledger_path=ledger
                )

            result = run_paper_carry_for_duration(
                fetch_inputs=fetch,
                min_net_apr=cfg.carry.min_net_apr,
                duration_seconds=float(params.get("duration_hours", 0.0)) * 3600,
                interval_seconds=float(params.get("interval_seconds", 300.0)),
                config=PaperCarryConfig(),
                on_cycle=persist,
            )
            record["result"] = {"paths": paths, "decisions": len(result.state.decisions)}
        elif kind == "ingest_job":
            outputs = {
                key: _checked_path(params[key], write=True)
                for key in ("raw_out", "out", "health", "state_dir", "report")
            }
            command = [
                str(Path(sys.executable).with_name("stonks-cli")),
                "run-ingest",
                "--duration-seconds",
                str(float(params.get("duration_seconds", 60.0))),
                "--raw-out",
                str(outputs["raw_out"]),
                "--out",
                str(outputs["out"]),
                "--health",
                str(outputs["health"]),
                "--state-dir",
                str(outputs["state_dir"]),
                "--report",
                str(outputs["report"]),
            ]
            if bool(params.get("allow_non_linux", False)):
                command.append("--allow-non-linux")
            for coin in params.get("coins") or ():
                command.extend(("--coin", str(coin)))
            completed = subprocess.run(
                command, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.returncode:
                raise RuntimeError(f"run-ingest failed with exit code {completed.returncode}")
            record["result"] = {"paths": {key: str(value) for key, value in outputs.items()}}
        record["status"] = "completed"
    except BaseException as error:
        record["status"] = "failed"
        record["error"] = str(error)
        raise
    finally:
        record["updated_at"] = _now().isoformat()
        _atomic_json(_job_path(job_id), record)


def _read_annotations() -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _write_annotations() -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


def create_server() -> FastMCP:
    mcp = FastMCP(
        SERVER_NAME,
        instructions="Paper-first research tools. No tool can place orders or arm live trading.",
        json_response=True,
    )

    @mcp.tool(name="status", annotations=_read_annotations())
    def status() -> dict[str, Any]:
        """Return local readiness and paper-first safety status."""
        return inspect_home()

    @mcp.tool(name="doctor", annotations=_read_annotations())
    def doctor(smoke: bool = False) -> dict[str, Any]:
        """Diagnose local configuration or run synthetic local smoke prerequisites."""
        return do_smoke_doctor() if smoke else do_doctor()

    @mcp.tool(name="config_get", annotations=_read_annotations())
    def config_get() -> dict[str, Any]:
        """Return effective configuration with sensitive values redacted."""
        return redacted_config_data(load_config())

    @mcp.tool(name="config_validate", annotations=_read_annotations())
    def config_validate() -> dict[str, object]:
        """Validate the effective configuration."""
        return do_config_validate()

    @mcp.tool(name="alert_preview", annotations=_read_annotations())
    def alert_preview(
        event: Literal["kill_switch", "stale_data", "ledger_mismatch", "service_restart"] = "service_restart",
    ) -> dict[str, Any]:
        """Render a synthetic carry alert; delivery is never attempted."""
        cfg = load_config()
        return {
            "delivery": "not_attempted",
            "event": event,
            "message": f"[synthetic] stonks-cli carry alert: {event}",
            "sink": cfg.carry.alert_sink,
            "synthetic": True,
        }

    @mcp.tool(name="crypto_universe", annotations=_read_annotations())
    def crypto_universe(snapshot: str) -> dict[str, Any]:
        """Read a strict persisted crypto-universe snapshot."""
        return load_crypto_universe_snapshot(_checked_path(snapshot)).to_data()

    @mcp.tool(name="crypto_rank", annotations=_read_annotations())
    def crypto_rank(components: str) -> list[dict[str, Any]]:
        """Rank persisted local crypto score components with configured weights."""
        cfg = load_config()
        if not cfg.vnext.enabled or not cfg.vnext.features.crypto_research:
            raise ValueError("vNext crypto-research ranking is not enabled")
        return [
            asdict(rank)
            for rank in rank_weighted_assets(
                _load_score_components(_checked_path(components)), cfg.vnext.research.factor_weights
            )
        ]

    @mcp.tool(name="portfolio_snapshot", annotations=_read_annotations())
    def portfolio_snapshot(snapshot: str) -> dict[str, object]:
        """Read a strict persisted portfolio snapshot without broker access."""
        return _portfolio_snapshot_to_data(_load_portfolio_snapshot(_checked_path(snapshot)))

    @mcp.tool(name="portfolio_daily_report", annotations=_read_annotations())
    def portfolio_daily_report(report_input: str) -> dict[str, str]:
        """Render a local daily portfolio-risk report without delivery."""
        cfg = load_config()
        if not cfg.vnext.enabled or not cfg.vnext.features.operator_reports:
            raise ValueError("vNext operator reports are not enabled")
        exposure, nav, confidence = _load_daily_report_inputs(_checked_path(report_input))
        return {"delivery": "not_attempted", "report": render_portfolio_risk_report(exposure, nav, confidence)}

    @mcp.tool(name="moomoo_accounts", annotations=_read_annotations())
    def moomoo_accounts() -> list[dict[str, Any]]:
        """Read accounts through an operator-managed local read-only Moomoo OpenD."""
        return [asdict(account) for account in import_moomoo_accounts(load_config())]

    @mcp.tool(name="moomoo_quotes", annotations=_read_annotations())
    def moomoo_quotes(symbols: list[str]) -> dict[str, Any]:
        """Refresh pre-entitled local Moomoo quotes without subscriptions or orders."""
        cfg = load_config()
        return {
            "broker": "moomoo",
            "endpoint": f"{cfg.vnext.moomoo.host}:{cfg.vnext.moomoo.port}",
            "read_only": True,
            "quotes": [asdict(quote) for quote in refresh_moomoo_market_data(cfg, symbols)],
        }

    @mcp.tool(name="moomoo_holdings", annotations=_read_annotations())
    def moomoo_holdings(
        account_id: str, account_index: int, trading_environment: str, captured_at: str
    ) -> dict[str, object]:
        """Import one read-only Moomoo holdings snapshot."""
        snapshot = import_moomoo_holdings(
            load_config(),
            MoomooAccount(account_id, account_index, trading_environment),
            datetime.fromisoformat(captured_at),
        )
        return _portfolio_snapshot_to_data(snapshot)

    @mcp.tool(name="reviewed_order_ticket", annotations=_read_annotations())
    def reviewed_order_ticket(
        ticket_id: str,
        account_id: str,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        limit_price: float,
        currency: str,
        rationale: str,
        prepared_at: str,
        reviewed_by: str,
        reviewed_at: str,
    ) -> dict[str, str]:
        """Render a reviewed manual-entry ticket; it cannot submit an order."""
        ticket = ReviewedOrderTicket(
            ticket_id,
            account_id,
            symbol,
            OrderTicketSide(side),
            OrderTicketType.LIMIT,
            quantity,
            limit_price,
            currency,
            rationale,
            datetime.fromisoformat(prepared_at),
            reviewed_by,
            datetime.fromisoformat(reviewed_at),
        )
        return {"execution": "manual broker-app entry required", "ticket": render_broker_app_order_ticket(ticket)}

    @mcp.tool(name="cli_readonly", annotations=_read_annotations())
    def cli_readonly(command: str, args: list[str] | None = None) -> dict[str, Any]:
        """Run an allowlisted non-mutating stonks-cli command without shell access."""
        supplied = list(args or [])
        _validate_readonly_cli_args(command, supplied)
        result = CliRunner().invoke(cli_app, [command, *supplied])
        return {"command": command, "exit_code": result.exit_code, "output": result.output}

    @mcp.tool(name="carry_scan", annotations=_read_annotations())
    def carry_scan(fixture: str | None = None, assets: list[str] | None = None) -> dict[str, Any]:
        """Scan paper carry opportunities; fixture input avoids network access."""
        cfg = load_config()
        inputs = load_carry_inputs_fixture(_checked_path(fixture)) if fixture else None
        rows = scan_hyperliquid_carry(
            cfg=cfg, inputs=inputs, assets=tuple(assets or ("BTC", "ETH")), assumptions=CarryCostAssumptions()
        )
        return {"paper": True, "rows": [row.to_dict() for row in rows]}

    @mcp.tool(name="research_rank_wallets", annotations=_read_annotations())
    def research_rank_wallets(fixture: str | None = None, limit: int = 100) -> dict[str, Any]:
        """Rank reproducible wallet attribution fixtures."""
        path = _checked_path(fixture or DEFAULT_ATTRIBUTION_FIXTURE)
        return {
            "fixture_path": str(path),
            "rankings": [row.to_dict() for row in rank_wallets_from_fixture(path, limit=limit)],
        }

    @mcp.tool(name="research_replay_paper", annotations=_read_annotations())
    def research_replay_paper(
        fixture: str | None = None, rankings_fixture: str | None = None, bankroll: float = 1000.0
    ) -> dict[str, Any]:
        """Replay synthetic paper analysis without trading."""
        paper = _checked_path(fixture or DEFAULT_PAPER_MIRROR_FIXTURE)
        rankings_path = _checked_path(rankings_fixture or DEFAULT_ATTRIBUTION_FIXTURE)
        replay = replay_paper_analysis_fixture(
            fixture_path=paper,
            rankings=rank_wallets_from_fixture(rankings_path, limit=5),
            config=PaperAnalysisConfig(follower_bankroll_usd=bankroll),
        )
        return {"tearsheet": replay.tearsheet, "decisions": [item.ledger_record.to_dict() for item in replay.decisions]}

    @mcp.tool(name="carry_preflight", annotations=_read_annotations())
    def carry_preflight(
        paper_gate_passed: bool = False,
        legal_review_recorded: bool = False,
        venue_health_ok: bool = False,
        manual_cap_confirmed: bool = False,
        requested_notional_usd: float = 0.0,
        cap_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Report live-preflight blockers without authorizing execution."""
        return evaluate_carry_live_preflight(
            cfg=load_config(),
            evidence=CarryLivePreflightEvidence(
                paper_gate_passed=paper_gate_passed,
                legal_review_recorded=legal_review_recorded,
                venue_health_ok=venue_health_ok,
                manual_cap_confirmed=manual_cap_confirmed,
                requested_notional_usd=requested_notional_usd,
                cap_usd=cap_usd,
            ),
        ).to_dict()

    @mcp.tool(name="carry_health", annotations=_read_annotations())
    def carry_health(state_dir: str, ledger: str, skip_network: bool = True) -> dict[str, Any]:
        """Check paper-carry artifacts and optionally venue network health."""
        report = build_carry_health_report(
            cfg=load_config(),
            state_dir=_checked_path(state_dir),
            ledger_path=_checked_path(ledger),
            skip_network=skip_network,
        )
        return report.to_dict()

    @mcp.tool(name="capture_gate_status", annotations=_read_annotations())
    def capture_gate_status(state_dir: str | None = None) -> dict[str, Any]:
        """Return persisted Hyperliquid capture-gate status."""
        root = _checked_path(state_dir) if state_dir else default_state_dir() / "validation-gates"
        path = gate_state_path(state_dir=root)
        if not path.exists():
            return {"state_path": str(path), "status": "not_started"}
        state = load_gate_state(state_dir=root)
        return {"state_path": str(path), "assessment": assess_gate(state).to_dict()}

    @mcp.tool(name="prepare_mutation", annotations=_write_annotations())
    def prepare_mutation(
        kind: Literal[
            "config_onboard",
            "config_update",
            "clean",
            "uninstall",
            "fixture_ledger",
            "fixture_ingest",
            "fixture_capture_gate",
            "carry_paper_job",
            "ingest_job",
            "cancel_job",
        ],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Preview a write/delete action and return a one-time confirmation ID."""
        return _prepare(kind, params)

    @mcp.tool(name="confirm_mutation", annotations=_write_annotations())
    def confirm_mutation(confirmation_id: str) -> dict[str, Any]:
        """Execute one prepared mutation exactly once."""
        return _confirm(confirmation_id)

    @mcp.tool(name="job_status", annotations=_read_annotations())
    def job_status(job_id: str) -> dict[str, Any]:
        """Return a persisted paper/capture job record."""
        record = _job_record(job_id)
        if not record:
            raise ValueError("unknown job_id")
        return record

    @mcp.tool(name="job_list", annotations=_read_annotations())
    def job_list() -> list[dict[str, Any]]:
        """List managed local jobs."""
        return [_load_json(path, {}) for path in sorted(_jobs_root().glob("*.json"))]

    return mcp


class _BearerApp:
    def __init__(self, app: Any, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            if not secrets.compare_digest(supplied, f"Bearer {self.token}"):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="stonks-cli MCP server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker")
    args = parser.parse_args(argv)
    if args.worker:
        _run_worker(args.worker)
        return
    server = create_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("streamable HTTP must bind to a loopback host")
    token = os.getenv("STONKS_CLI_MCP_TOKEN")
    if not token:
        raise SystemExit("STONKS_CLI_MCP_TOKEN is required for streamable HTTP")
    import uvicorn

    uvicorn.run(_BearerApp(server.streamable_http_app(), token), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
