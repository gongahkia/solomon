# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".sh", ".ts", ".yml", ".yaml"}
SKIP_PARTS = {".git", ".venv", "dist", "node_modules", "__pycache__"}
HEADER = "SPDX-License-Identifier: Apache-2.0"


def _has_header(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()[:3]
    return any(HEADER in line for line in lines)


def main() -> int:
    missing = [
        path.relative_to(ROOT)
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not any(part in SKIP_PARTS for part in path.parts)
        and not _has_header(path)
    ]
    if missing:
        print("missing SPDX license header:")
        print("\n".join(str(path) for path in sorted(missing)))
        return 1
    print("license headers: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
