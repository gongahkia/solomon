# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_production_compose_declares_required_services_and_secrets() -> None:
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")

    for service in ("postgres:", "migrations:", "api:", "console:", "worker:"):
        assert f"  {service}" in compose
    assert "pgvector/pgvector:0.8.2-pg16-bookworm" in compose
    assert "service_healthy" in compose
    assert "service_completed_successfully" in compose
    assert "SOLOMON_SERVER_API_KEY_FILE" in compose
    assert "SOLOMON_CONSOLE_BEARER_TOKEN_FILE" in compose
    assert "SOLOMON_CONSOLE_ROLE: admin" in compose
    assert "SOLOMON_CONTENT_ENCRYPTION_KEY_FILE" in compose
    assert "POSTGRES_PASSWORD_FILE" in compose


def test_production_surface_ci_matrix_and_smoke_harness() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    smoke = ROOT / "scripts" / "production_compose_smoke.sh"

    assert smoke.is_file()
    assert smoke.stat().st_mode & 0o111
    for fragment in (
        "typescript-sdk:",
        "npm test",
        "postgres-pgvector-migrations:",
        "pgvector/pgvector:0.8.2-pg16-bookworm",
        "tests/test_migrations.py tests/test_postgres_live_integration.py",
        "production-compose-smoke:",
        "scripts/production_compose_smoke.sh",
        "helm-template:",
        "azure/setup-helm@v5",
        "scripts/check_helm_chart.sh",
    ):
        assert fragment in workflow
    for fragment in (
        "up --build --detach --wait --wait-timeout 240",
        "curl --fail --silent --show-error",
        "Authorization: Bearer test-console-bearer-token",
        '"http://$console_endpoint/console/sources"',
        "down --volumes --remove-orphans",
    ):
        assert fragment in smoke.read_text(encoding="utf-8")


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is required for Compose schema validation")
def test_production_compose_validates_with_docker() -> None:
    result = subprocess.run(  # noqa: S603 - test invokes a repository-controlled script
        ["/bin/sh", str(ROOT / "scripts/check_production_compose.sh")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
