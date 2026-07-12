# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import sys
from pathlib import Path

CONVENTIONAL_SUBJECT = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([a-z0-9._/-]+\))?!?: .+"
)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("expected a commit-message file")
        return 2
    subject = Path(argv[1]).read_text(encoding="utf-8").splitlines()[0]
    if CONVENTIONAL_SUBJECT.fullmatch(subject):
        return 0
    print("commit subject must use Conventional Commits, for example: feat: add currency report")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
