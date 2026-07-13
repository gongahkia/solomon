# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_helm_chart_declares_production_surfaces() -> None:
    chart = ROOT / "charts/solomon"
    values = (chart / "values.yaml").read_text(encoding="utf-8")

    assert (chart / "Chart.yaml").is_file()
    assert (chart / "values.schema.json").is_file()
    for template in ("api.yaml", "console.yaml", "worker.yaml", "migrations.yaml", "postgresql.yaml", "ingress.yaml"):
        assert (chart / "templates" / template).is_file()
    for value in ("auth:", "postgresql:", "observability:", "persistence:"):
        assert value in values


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is required for chart validation")
def test_helm_chart_lints_and_renders() -> None:
    result = subprocess.run(  # noqa: S603 - test invokes a repository-controlled script
        ["/bin/sh", str(ROOT / "scripts/check_helm_chart.sh")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
