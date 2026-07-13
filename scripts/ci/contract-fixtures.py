#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate versioned cross-surface contract fixture manifests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts" / "ci" / "contract-fixtures.json"
REQUIRED_SURFACES = {"rust", "python", "node", "http"}


def main() -> int:
    manifest = load_json(MANIFEST)
    require(manifest.get("schema_version") == 1, "unsupported manifest schema_version")
    require(manifest.get("contract") == "shibahama.memory", "unsupported contract")
    allowed_operations = set(manifest.get("allowed_operations", []))
    require(allowed_operations, "allowed_operations must not be empty")
    fixture_ids: set[str] = set()

    for fixture in manifest.get("fixtures", []):
        fixture_id = require_string(fixture, "id")
        require(fixture_id not in fixture_ids, f"duplicate fixture id: {fixture_id}")
        fixture_ids.add(fixture_id)
        require(fixture.get("schema_version") == 1, f"{fixture_id}: unsupported schema_version")
        require(
            REQUIRED_SURFACES.issubset(set(fixture.get("surfaces", []))),
            f"{fixture_id}: missing required surface",
        )
        operations = set(fixture.get("operations", []))
        require(operations, f"{fixture_id}: operations must not be empty")
        require(
            operations.issubset(allowed_operations),
            f"{fixture_id}: operations include unknown values",
        )
        path = ROOT / require_string(fixture, "path")
        payload = load_json(path)
        require(payload.get("schema_version") == fixture["schema_version"], f"{fixture_id}: schema mismatch")
        require(payload.get("contract") == manifest["contract"], f"{fixture_id}: contract mismatch")

    require(fixture_ids, "fixtures must not be empty")
    print(f"contract fixtures valid: {', '.join(sorted(fixture_ids))}")
    return 0


def load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid contract fixture {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid contract fixture {path}: expected object")
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"missing or invalid {key}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
