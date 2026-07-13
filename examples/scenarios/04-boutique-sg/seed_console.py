# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from run import _seed_scenario

ROOT = Path("/app")
DATABASE = ROOT / "data" / "solomon.sqlite3"


def main() -> int:
    if DATABASE.exists():
        print("boutique scenario already seeded")
        return 0
    _seed_scenario(ROOT)
    print("boutique scenario seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
