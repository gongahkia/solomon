# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path("scripts/check_conventional_commit.py")


def _load_checker() -> object:
    specification = importlib.util.spec_from_file_location("conventional_commit_checker", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("subject", "expected"),
    (
        ("feat: add governed assertions", True),
        ('Revert "feat: add conservative reliance semantics grammar"', True),
        ('Revert "revert(api): restrict assertion confirmation"', True),
        ('Revert "add governed assertions"', False),
        ("Revert feat: add governed assertions", False),
        ('Revert "feat: "', False),
        ("restore the parser", False),
    ),
)
def test_conventional_commit_checker_accepts_only_standard_git_reverts(subject: str, expected: bool) -> None:
    checker = _load_checker()

    assert checker.is_valid_commit_subject(subject) is expected
