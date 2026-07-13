# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from pathlib import Path

ALLOWLIST = {
    Path("src/solomon/api/app.py"): "public FastAPI route facade retained while routes move to focused modules",
    Path("src/solomon/api/service.py"): "public service facade retained for stable API, CLI, MCP, and test imports",
    Path(
        "src/solomon/audit/journal.py"
    ): "tamper-evident journal persistence and verification stay transactionally cohesive",
    Path("src/solomon/cli/main.py"): "CLI command registration remains a stable public entrypoint",
    Path(
        "src/solomon/console/app.py"
    ): "console route and rendering facade remains cohesive while first-class workflows are completed",
    Path("src/solomon/evaluation.py"): "benchmark harness slated for W7 split",
    Path("src/solomon/graph/suggestions.py"): "dependency extraction variants pending W16 graph work",
    Path(
        "src/solomon/orchestrator/retrieval.py"
    ): "retrieval fusion and context assembly retain shared ranking invariants",
    Path("src/solomon/sources/store.py"): "source lifecycle persistence remains a single transactional implementation",
    Path("src/solomon/store/sqlite.py"): "SQLite append-only store remains a single transactional implementation",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when Solomon source files exceed the configured line budget.")
    parser.add_argument("--root", type=Path, default=Path("src/solomon"))
    parser.add_argument("--max-lines", type=int, default=500)
    args = parser.parse_args()

    failures: list[str] = []
    for path in sorted(args.root.rglob("*.py")):
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count <= args.max_lines or path in ALLOWLIST:
            continue
        failures.append(f"{path}: {count} lines > {args.max_lines}")
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
