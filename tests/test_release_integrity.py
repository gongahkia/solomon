from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tracked_source_and_docs_have_no_merge_markers():
    markers = ("<<<<<<<", "=======", ">>>>>>>")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for raw_path in tracked:
        path = ROOT / raw_path
        if not raw_path or path.suffix not in {".md", ".py", ".sh", ".toml", ".yml", ".yaml"}:
            continue
        assert not any(line.startswith(markers) for line in path.read_text(encoding="utf-8").splitlines()), path
