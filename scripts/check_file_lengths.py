# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from pathlib import Path

# benchmark harness owns a broad set of generated/evaluation helpers pending W7.
ALLOWLIST = {
    Path("src/solomon/evaluation.py"): "benchmark harness slated for W7 split",
    # ASGI routes/templates share request-local helpers pending console tier decision in W15.
    Path("src/solomon/console/app.py"): "secondary console surface pending W15 scope decision",
    # deterministic parser/scorer variants stay together until contradiction work in W16.
    Path("src/solomon/graph/suggestions.py"): "dependency extraction variants pending W16 graph work",
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
