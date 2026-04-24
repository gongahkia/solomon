from __future__ import annotations

from stonks_cli.logging_utils import track_event
from stonks_cli.polymarket.client import utc_now_iso
from stonks_cli.polymarket.models import RuntimeStatus
from stonks_cli.polymarket.scanner import StructuralScanConfig, scan_markets
from stonks_cli.polymarket.storage import load_runtime_status, save_runtime_status


def runtime_status() -> RuntimeStatus:
    return load_runtime_status()


def run_structural_scan_once(client, *, limit: int, cfg: StructuralScanConfig, paper: bool) -> tuple[RuntimeStatus, list]:
    try:
        scans = scan_markets(client, limit=limit, cfg=cfg, include_filtered=False)
        status = RuntimeStatus(
            mode="polymarket",
            state="idle",
            paper=paper,
            last_scan_at=utc_now_iso(),
            last_scan_count=limit,
            last_pass_count=len(scans),
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
