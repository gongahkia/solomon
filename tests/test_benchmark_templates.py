from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli.benchmark_templates import get_template, list_templates
from stonks_cli.cli import app


def test_template_catalog_covers_required_reference_categories() -> None:
    templates = {template.identifier: template for template in list_templates()}

    assert set(templates) == {
        "us-sg-core",
        "global-equity",
        "global-reit",
        "us-dividend",
        "us-bond-core",
    }
    assert get_template("GLOBAL-EQUITY") == templates["global-equity"]
    for template in templates.values():
        assert template.components
        assert template.coverage
        assert template.return_methodology
        assert template.cost_availability
        assert template.diversification
        assert template.pros
        assert template.cons
        assert template.source_provenance
        assert template.retrieved_at == "2026-07-23T00:00:00+00:00"


def test_cli_lists_templates_and_requires_total_return_data_before_template_activation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    key = tmp_path / "key"
    assert runner.invoke(app, ["init-profile", "personal", "--key-file", str(key)]).exit_code == 0

    listed = runner.invoke(app, ["benchmark-templates"])
    assert listed.exit_code == 0, listed.output
    catalog = json.loads(listed.output)
    assert catalog["informational_only"] is True
    assert catalog["templates"][1]["source_provenance"] == ["MSCI"]
    unavailable = runner.invoke(app, ["benchmark-template-import", "personal", "global-equity"])
    assert unavailable.exit_code == 1, unavailable.output
    assert json.loads(unavailable.output)["missing_total_return_components"] == ["GLOBAL:ACWI"]

    source = tmp_path / "returns.csv"
    source.write_text(
        "date,identifier,currency,total_return_index\n2026-01-02,GLOBAL:ACWI,USD,100\n"
    )
    assert runner.invoke(app, ["import-benchmark-total-returns", "personal", str(source)]).exit_code == 0
    imported = runner.invoke(app, ["benchmark-template-import", "personal", "global-equity"])

    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.output)["configuration_version"] == 2
    audit = runner.invoke(app, ["benchmark-audit", "personal"])
    assert audit.exit_code == 0, audit.output
    record = json.loads(audit.output)["records"][0]
    assert record["origin"] == "global-equity"
    assert record["source_provenance"] == ["MSCI"]
    assert record["data_status"] == "available"
