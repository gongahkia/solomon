#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

if git rev-parse --verify --quiet HEAD >/dev/null; then
  mapfile -t files < <(git ls-files)
else
  mapfile -t files < <(find . -type f -not -path './.git/*' -print)
fi

if ((${#files[@]} == 0)); then
  exit 0
fi

python3 - "${files[@]}" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    ("OpenAI API key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("generic assignment secret", re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{16,}['\"]")),
)

BINARY_EXTENSIONS = {
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".lock",
    ".png",
    ".webp",
}

failures: list[str] = []

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    if not path.is_file() or path.suffix.lower() in BINARY_EXTENSIONS:
        continue

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue

    for name, pattern in PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            failures.append(f"{path}:{line}: possible {name}")

if failures:
    print("Secret scan failed:", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    raise SystemExit(1)

print("secret scan passed")
PY
