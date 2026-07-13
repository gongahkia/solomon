# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _run_command(
    command: list[str], args: list[str], environment: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    full_command = [*command, *args]
    try:
        return subprocess.run(  # noqa: S603
            full_command,
            capture_output=True,
            check=True,
            cwd=cwd,
            env=environment,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"command failed: {' '.join(full_command)}\n{exc.stderr.strip()}") from exc


def _run_json(command: list[str], args: list[str], environment: dict[str, str], cwd: Path) -> dict[str, Any]:
    completed = _run_command(command, args, environment, cwd)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command did not emit JSON: {' '.join([*command, *args])}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"command did not emit a JSON object: {' '.join([*command, *args])}")
    return payload


def _run_text(command: list[str], args: list[str], environment: dict[str, str], cwd: Path) -> str:
    return _run_command(command, args, environment, cwd).stdout.strip()


def _scenario_environment(root: Path, *, server_sku: bool) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "SOLOMON_DATA_DIR": str(root / "data"),
            "SOLOMON_JOURNAL_DIR": str(root / "journal"),
            "SOLOMON_ZERO_EGRESS_MODE": "true",
        }
    )
    if server_sku:
        environment.update(
            {
                "SOLOMON_SKU": "server",
                "SOLOMON_SERVER_AUTH_MODE": "legacy-api-key",
                "SOLOMON_SERVER_API_KEY": "ci-local-binary-smoke",
            }
        )
    else:
        environment["SOLOMON_SKU"] = "local"
        environment.pop("SOLOMON_SERVER_AUTH_MODE", None)
        environment.pop("SOLOMON_SERVER_API_KEY", None)
    return environment


def _scenario_summary(command: list[str], root: Path, *, server_sku: bool) -> dict[str, Any]:
    root.mkdir(parents=True)
    environment = _scenario_environment(root, server_sku=server_sku)
    version = _run_text(command, ["--version"], environment, root)
    item = _run_json(
        command,
        [
            "ingest",
            "2023 house view: structure X is compliant under Regulation R section 12 for Client A.",
            "--source-ref",
            "house-view-2023",
            "--kind",
            "house-view",
            "--source-kind",
            "partner",
        ],
        environment,
        root,
    )
    item_id = item.get("id")
    if not isinstance(item_id, str):
        raise RuntimeError("ingest response did not include an item id")
    _ = _run_json(
        command,
        [
            "add-dependency",
            "--source-id",
            item_id,
            "--target-id",
            "reg-r-12",
            "--edge-type",
            "internal_depends_on_external",
        ],
        environment,
        root,
    )
    impact = _run_json(
        command,
        [
            "register-authority-change",
            "reg-r-12",
            "--new-version",
            "2025-amendment",
            "--changed-at",
            "2025-01-01T00:00:00+00:00",
        ],
        environment,
        root,
    )
    currency = _run_json(command, ["check-currency", item_id], environment, root)
    stale_reasons = currency.get("stale_reasons")
    stale_item_ids = impact.get("stale_item_ids")
    if not isinstance(stale_reasons, list) or not isinstance(stale_item_ids, list):
        raise RuntimeError("stale-house-view output did not contain expected lists")
    return {
        "version": version,
        "currency_state": currency.get("currency_state"),
        "explanation": currency.get("explanation"),
        "verification_due": currency.get("verification_due"),
        "stale_item_count": len(stale_item_ids),
        "stale_reasons": [
            {
                "changed_at": reason.get("changed_at"),
                "dependency_id": reason.get("dependency_id"),
                "reason": reason.get("reason"),
            }
            for reason in stale_reasons
            if isinstance(reason, dict)
        ],
    }


def _validate_stale_house_view(summary: dict[str, Any]) -> None:
    expected_reason = {
        "changed_at": "2025-01-01T00:00:00Z",
        "dependency_id": "reg-r-12",
        "reason": "external authority reg-r-12 changed to version 2025-amendment",
    }
    if summary["currency_state"] != "StalePendingReverification":
        raise RuntimeError(f"unexpected currency state: {summary['currency_state']}")
    if summary["stale_item_count"] != 1:
        raise RuntimeError(f"unexpected stale item count: {summary['stale_item_count']}")
    if summary["stale_reasons"] != [expected_reason]:
        raise RuntimeError(f"unexpected stale reasons: {summary['stale_reasons']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the offline binary with the server-SKU CLI scenario output.")
    parser.add_argument("--binary", type=Path, required=True, help="Path to the built solomon-local executable.")
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"binary is not executable: {binary}")

    with tempfile.TemporaryDirectory(prefix="solomon-local-binary-smoke-") as temporary_directory:
        root = Path(temporary_directory)
        server_summary = _scenario_summary([sys.executable, "-m", "solomon.cli.main"], root / "server", server_sku=True)
        binary_summary = _scenario_summary([str(binary)], root / "local", server_sku=False)
    _validate_stale_house_view(server_summary)
    _validate_stale_house_view(binary_summary)
    if binary_summary != server_summary:
        raise RuntimeError(
            f"local binary output diverged from server-SKU CLI: binary={binary_summary} server={server_summary}"
        )
    print(json.dumps({"binary": str(binary), "scenario": binary_summary, "status": "ok"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
