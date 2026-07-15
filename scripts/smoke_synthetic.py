#!/usr/bin/env python3
"""Run isolated, synthetic CLI and MCP smoke checks without network access."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _carry_fixture(path: Path) -> None:
    payload = {
        "inputs": [
            {
                "asset": "BTC",
                "quote": {
                    "venue": "hyperliquid",
                    "asset": "BTC",
                    "spot_mid": 100000.0,
                    "perp_mid": 100100.0,
                    "oracle_mid": 100050.0,
                    "mark_mid": 100090.0,
                    "timestamp": "2026-07-02T00:00:00Z",
                    "source_health": "ok",
                },
                "funding": {
                    "asset": "BTC",
                    "venue": "hyperliquid",
                    "hourly_rate": 0.22 / (24 * 365),
                    "annualized_rate": 0.22,
                    "next_funding_time": None,
                    "premium_index": 0.001,
                    "timestamp": "2026-07-02T00:00:00Z",
                },
                "basis": {
                    "asset": "BTC",
                    "spot_mid": 100000.0,
                    "perp_mid": 100100.0,
                    "basis_abs": 100.0,
                    "basis_pct": 0.001,
                    "annualized_basis": 0.0,
                    "timestamp": "2026-07-02T00:00:00Z",
                },
                "metadata": {"perp": {"name": "BTC"}, "spot": {"name": "BTC/USDC"}},
                "source_health": {"all_mids": "ok", "perp_context": "ok", "spot_context": "ok"},
            }
        ]
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_cli(env: dict[str, str], *args: str, expect_json: bool = True) -> Any:
    completed = subprocess.run(
        ["uv", "run", "stonks-cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"CLI failed ({' '.join(args)}): {completed.stderr or completed.stdout}")
    if not expect_json:
        return completed.stdout
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"CLI did not emit JSON ({' '.join(args)}): {completed.stdout}") from error


async def _run_mcp(env: dict[str, str], fixture: Path, output: Path) -> dict[str, Any]:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "stonks_cli.mcp_server"], env=env, cwd=ROOT)
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                required = {
                    "alert_preview",
                    "status",
                    "carry_scan",
                    "research_rank_wallets",
                    "prepare_mutation",
                    "confirm_mutation",
                }
                if not required <= names:
                    raise RuntimeError(f"MCP tools missing: {sorted(required - names)}")
                status = await session.call_tool("status", {})
                scan = await session.call_tool("carry_scan", {"fixture": str(fixture)})
                prepared = await session.call_tool(
                    "prepare_mutation",
                    {
                        "kind": "fixture_ingest",
                        "params": {
                            "fixture": str(ROOT / "tests/fixtures/research/hyperliquid-ws.jsonl"),
                            "out": str(output),
                        },
                    },
                )
                confirmation_id = prepared.structuredContent["confirmation_id"]
                confirmed = await session.call_tool("confirm_mutation", {"confirmation_id": confirmation_id})
                return {
                    "tool_count": len(names),
                    "status": status.structuredContent,
                    "scan": scan.structuredContent,
                    "ingest": confirmed.structuredContent,
                }


def main() -> None:
    smoke_root = Path(os.environ.get("STONKS_CLI_SMOKE_ROOT") or tempfile.mkdtemp(prefix="stonks-cli-smoke-"))
    smoke_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "STONKS_CLI_HOME": str(smoke_root / "app"),
            "STONKS_CLI_CONFIG": str(smoke_root / "app" / "config.json"),
            "STONKS_CLI_MCP_ROOTS": os.pathsep.join((str(ROOT), str(smoke_root))),
        }
    )
    fixture = smoke_root / "carry-inputs.json"
    _carry_fixture(fixture)
    artifacts = smoke_root / "artifacts"
    artifacts.mkdir()
    _run_cli(env, "init-config", "--path", env["STONKS_CLI_CONFIG"], expect_json=False)
    home = _run_cli(env, "home", "--json")
    validation = _run_cli(env, "validate-config")
    ingest = _run_cli(
        env,
        "replay-ingest",
        "--fixture",
        "tests/fixtures/research/hyperliquid-ws.jsonl",
        "--out",
        str(artifacts / "normalized.jsonl"),
    )
    wallets = _run_cli(env, "rank-wallet", "--fixture", "tests/fixtures/research/wallet-attribution.jsonl")
    paper = _run_cli(
        env,
        "replay-paper",
        "--fixture",
        "tests/fixtures/research/paper-mirror.jsonl",
        "--rankings-fixture",
        "tests/fixtures/research/wallet-attribution.jsonl",
    )
    ledger = _run_cli(
        env, "demo-ledger", "--ledger", str(artifacts / "ledger.md"), "--tearsheet", str(artifacts / "tearsheet.md")
    )
    carry = _run_cli(
        env,
        "run-carry-paper",
        "--fixture",
        str(fixture),
        "--duration-hours",
        "0",
        "--state-dir",
        str(artifacts / "carry"),
        "--report",
        str(artifacts / "carry/report.md"),
        "--ledger",
        str(artifacts / "carry/ledger.md"),
    )
    if home["safety"]["live_execution"] != "blocked" or not validation["valid"]:
        raise RuntimeError("paper-first safety invariant failed")
    if (
        ingest["health"]["dropped_messages"] != 1
        or len(wallets["rankings"]) != 3
        or paper["tearsheet"]["closed_trades"] != 2
    ):
        raise RuntimeError("synthetic research fixture expectations changed")
    for output in (
        artifacts / "normalized.jsonl",
        artifacts / "ledger.md",
        artifacts / "tearsheet.md",
        artifacts / "carry/report.md",
        artifacts / "carry/ledger.md",
    ):
        if not output.exists():
            raise RuntimeError(f"missing smoke artifact: {output}")
    mcp = asyncio.run(_run_mcp(env, fixture, artifacts / "mcp-normalized.jsonl"))
    if mcp["status"]["safety"]["live_execution"] != "blocked" or not (artifacts / "mcp-normalized.jsonl").exists():
        raise RuntimeError("MCP smoke invariant failed")
    manifest = {
        "app_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "not_validation_evidence": True,
        "fixtures": {
            "carry_inputs": _sha256(fixture),
            "hyperliquid_ws": _sha256(ROOT / "tests/fixtures/research/hyperliquid-ws.jsonl"),
            "paper_mirror": _sha256(ROOT / "tests/fixtures/research/paper-mirror.jsonl"),
            "wallet_attribution": _sha256(ROOT / "tests/fixtures/research/wallet-attribution.jsonl"),
        },
        "config_sha256": _sha256(Path(env["STONKS_CLI_CONFIG"])),
        "artifacts": {
            path.relative_to(smoke_root).as_posix(): _sha256(path)
            for path in sorted(artifacts.rglob("*"))
            if path.is_file()
        },
        "cli": {"home": home, "validation": validation, "carry": carry, "ledger": ledger},
        "mcp": {"tool_count": mcp["tool_count"], "ingest": mcp["ingest"]},
    }
    manifest_path = smoke_root / "smoke-provenance.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps({"smoke_root": str(smoke_root), "provenance": str(manifest_path), "synthetic": True}, sort_keys=True)
    )


if __name__ == "__main__":
    main()
