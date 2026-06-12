# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from solomon import __version__
from solomon.cli.main import app
from solomon.config import get_settings

runner = CliRunner()


def _configure_cli_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SOLOMON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOLOMON_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setenv("SOLOMON_VERIFICATION_ATTESTATION_KEY", "test-secret")
    get_settings.cache_clear()


def test_cli_version_and_diagnostics(monkeypatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)

    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.output.strip() == __version__

    diagnostics = runner.invoke(app, ["diagnostics"])
    assert diagnostics.exit_code == 0
    payload = json.loads(diagnostics.output)

    assert payload["version"] == __version__
    assert payload["settings"]["data_dir"] == str(tmp_path / "data")
    assert payload["settings"]["journal_dir"] == str(tmp_path / "journal")
    assert payload["kaypoh"]["importable"] is True


def test_cli_ingest_recall_and_why_use_same_local_store(monkeypatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)

    ingest = runner.invoke(
        app,
        [
            "ingest",
            "reg r structure x",
            "--source-ref",
            "memo-cli",
            "--kind",
            "position",
            "--source-kind",
            "partner",
        ],
    )
    assert ingest.exit_code == 0
    item = json.loads(ingest.output)
    assert item["id"]
    assert item["provenance"]["source_ref"] == "memo-cli"

    recall = runner.invoke(app, ["recall", "reg r structure", "--review-mode"])
    assert recall.exit_code == 0
    results = json.loads(recall.output)
    assert results[0]["item"]["id"] == item["id"]
    assert results[0]["currency_state"] == "Live"

    why = runner.invoke(app, ["why", item["id"]])
    assert why.exit_code == 0
    assert item["id"] in why.output
    assert "credence: FirmAuthoritative" in why.output
    assert "source: memo-cli" in why.output
