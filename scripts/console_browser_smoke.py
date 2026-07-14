# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType

PLAYWRIGHT_CLI_VERSION = "0.1.17"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _seed_stale_item(root: Path) -> None:
    service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.HOUSE_VIEW,
            content="2023 house view: structure X is compliant under Regulation R section 12 for Client A.",
            source_kind=SourceKind.PARTNER,
            source_ref="house-view-2023",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="2025-amendment", changed_at="2025-01-01T00:00:00+00:00"),
    )


def _wait_for_server(url: str, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if server.poll() is not None:
            output = server.stdout.read() if server.stdout is not None else ""
            raise RuntimeError(f"console server exited during startup:\n{output}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except urllib.error.URLError:
            time.sleep(0.2)
    raise RuntimeError("console server did not become healthy within 20 seconds")


def _run_cli(command: list[str], session: str, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603
        [*command, f"-s={session}", *args],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Playwright command failed: {' '.join(args)}\n{completed.stdout}\n{completed.stderr}")
    return completed.stdout


def _snapshot(command: list[str], session: str) -> str:
    return _run_cli(command, session, "snapshot")


def _ref(snapshot: str, role: str, name: str) -> str:
    match = re.search(rf'{re.escape(role)} "{re.escape(name)}" \[ref=([^\]]+)\]', snapshot)
    if match is None:
        raise RuntimeError(f"could not find {role} {name!r} in browser snapshot:\n{snapshot}")
    return match.group(1)


def _require_text(snapshot: str, text: str) -> None:
    if text not in snapshot:
        raise RuntimeError(f"browser snapshot did not contain {text!r}:\n{snapshot}")


def _run_verification_flow(command: list[str], session: str, url: str) -> None:
    _run_cli(command, session, "open", url)
    initial = _snapshot(command, session)
    _require_text(initial, "StalePendingReverification")
    _run_cli(command, session, "fill", _ref(initial, "textbox", "Reviewer id"), "Partner A")
    _run_cli(command, session, "fill", _ref(initial, "textbox", "Assigned by"), "PSL")
    _run_cli(command, session, "fill", _ref(initial, "textbox", "Basis"), "authority changed")
    _run_cli(command, session, "click", _ref(initial, "button", "Assign reviewer"))

    assigned = _snapshot(command, session)
    _require_text(assigned, "Partner A")
    _require_text(assigned, "assigned")
    _run_cli(command, session, "fill", _ref(assigned, "textbox", "Evidence ref"), "memo-2026-01")
    _run_cli(command, session, "fill", _ref(assigned, "textbox", "Partner id"), "Partner A")
    _run_cli(command, session, "click", _ref(assigned, "button", "Submit decision"))

    reaffirmed = _snapshot(command, session)
    _require_text(reaffirmed, "Live")
    _require_text(reaffirmed, "reaffirmed")
    _require_text(reaffirmed, "memo-2026-01")


def _run_navigation_smoke(command: list[str], session: str, base_url: str) -> None:
    for path, heading in (
        ("/console/claims", "Claim Promotion"),
        ("/console/sources", "Sources"),
        ("/console/reviews", "Review Tasks"),
        ("/console/dependencies", "Dependency Review"),
        ("/console/currency-report", "Currency Report"),
        ("/console/audit-pack", "Audit Pack"),
    ):
        _run_cli(command, session, "open", f"{base_url}{path}")
        _require_text(_snapshot(command, session), heading)


def _cli_command(playwright_cli: Path | None) -> list[str]:
    if playwright_cli is not None:
        return [str(playwright_cli)]
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx is required for the console browser smoke")
    return [npx, "--yes", "--package", f"@playwright/cli@{PLAYWRIGHT_CLI_VERSION}", "playwright-cli"]


def _stop_server(server: subprocess.Popen[str]) -> None:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the curator console verification flow in a real browser.")
    parser.add_argument("--playwright-cli", type=Path, help="Path to a Playwright CLI wrapper for local runs.")
    args = parser.parse_args()
    if args.playwright_cli is not None and not args.playwright_cli.is_file():
        raise RuntimeError(f"Playwright CLI wrapper does not exist: {args.playwright_cli}")

    command = _cli_command(args.playwright_cli)
    session = f"solomon-console-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="solomon-console-browser-") as temporary_directory:
        root = Path(temporary_directory)
        _seed_stale_item(root)
        port = _free_port()
        environment = os.environ.copy()
        environment.update(
            {
                "SOLOMON_DATA_DIR": str(root / "data"),
                "SOLOMON_JOURNAL_DIR": str(root / "journal"),
            }
        )
        server = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "uvicorn",
                "solomon.console.app:create_console_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=environment,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_server(f"http://127.0.0.1:{port}/health", server)
            base_url = f"http://127.0.0.1:{port}"
            _run_verification_flow(command, session, f"{base_url}/console/verification")
            _run_navigation_smoke(command, session, base_url)
        finally:
            try:
                _run_cli(command, session, "close")
            finally:
                _stop_server(server)
    print("console browser smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
