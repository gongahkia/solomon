# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_spec_targets_local_cli_binary() -> None:
    spec_path = ROOT / "packaging" / "solomon-local.spec"
    tree = ast.parse(spec_path.read_text(encoding="utf-8"))
    constants = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)]

    assert "solomon-local" in constants
    assert "main.py" in spec_path.read_text(encoding="utf-8")
    assert "src_root" in spec_path.read_text(encoding="utf-8")
    assert (ROOT / "src" / "solomon" / "cli" / "main.py").exists()


def test_packaging_docs_match_project_version_and_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    packaging_deps = pyproject["project"]["optional-dependencies"]["packaging"]
    docs = (ROOT / "packaging" / "README.md").read_text(encoding="utf-8")

    assert any(dependency.startswith("pyinstaller") for dependency in packaging_deps)
    assert f"dist/solomon-{version}.tar.gz" in docs
    assert f"dist/solomon-{version}-py3-none-any.whl" in docs
    assert "dist/solomon-local" in docs
