# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from solomon import __version__
from solomon.cli.main import app
from solomon.config import get_settings

runner = CliRunner()


def _configure_cli_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SOLOMON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOLOMON_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setenv("SOLOMON_VERIFICATION_ATTESTATION_KEY", "test-secret")
    get_settings.cache_clear()


def test_cli_version_and_diagnostics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    assert payload["boundary"]["importable"] is True


def test_cli_mcp_serve_dispatches_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("solomon.cli.main.run_stdio_server", lambda: calls.append("stdio"))

    result = runner.invoke(app, ["mcp", "serve"])

    assert result.exit_code == 0
    assert calls == ["stdio"]


def test_cli_mcp_serve_dispatches_http(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, int]] = []

    def run_http(*, host: str, port: int) -> None:
        calls.append(("http", host, port))

    monkeypatch.setattr("solomon.cli.main.run_streamable_http_server", run_http)

    result = runner.invoke(app, ["mcp", "serve", "--http", "--host", "127.0.0.2", "--port", "9000"])

    assert result.exit_code == 0
    assert calls == [("http", "127.0.0.2", 9000)]


def test_cli_mcp_serve_rejects_conflicting_http_modes() -> None:
    result = runner.invoke(app, ["mcp", "serve", "--http", "--sse"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_cli_help_includes_examples_for_visible_commands() -> None:
    commands = [
        ["diagnostics"],
        ["health"],
        ["ingest"],
        ["recall"],
        ["preflight"],
        ["check-currency"],
        ["impact"],
        ["get-dependencies"],
        ["dependency-graph"],
        ["extract-refs"],
        ["predict-stale"],
        ["register-authority-change"],
        ["add-dependency"],
        ["suggest-dependencies"],
        ["dependency-suggestions"],
        ["confirm-dependency-suggestion"],
        ["reject-dependency-suggestion"],
        ["verify-position"],
        ["why"],
        ["audit-pack"],
        ["mcp", "serve"],
        ["console", "serve"],
    ]

    top_level = runner.invoke(app, ["--help"])
    assert top_level.exit_code == 0
    assert "Example:" in top_level.output

    for command in commands:
        result = runner.invoke(app, [*command, "--help"])
        assert result.exit_code == 0, command
        assert "Example:" in result.output, command


def test_cli_console_serve_dispatches_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def run(app_path: str, **kwargs: object) -> None:
        calls.append({"app_path": app_path, **kwargs})

    monkeypatch.setattr("uvicorn.run", run)

    result = runner.invoke(app, ["console", "serve", "--host", "127.0.0.2", "--port", "8151", "--reload"])

    assert result.exit_code == 0
    assert calls == [
        {
            "app_path": "solomon.console.app:create_console_app",
            "factory": True,
            "host": "127.0.0.2",
            "port": 8151,
            "reload": True,
        }
    ]


def test_cli_ingest_recall_and_why_use_same_local_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_cli_mcp_aligned_verbs_and_migration_shims(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)

    health = runner.invoke(app, ["health"])
    assert health.exit_code == 0
    assert json.loads(health.output)["store"]["ok"] is True

    ingest = runner.invoke(
        app,
        [
            "ingest",
            "reg r section 12 governs structure x",
            "--source-ref",
            "memo-cli-aligned",
            "--kind",
            "position",
            "--source-kind",
            "partner",
        ],
    )
    assert ingest.exit_code == 0
    item = json.loads(ingest.output)

    preflight = runner.invoke(app, ["preflight", "reg r section 12"])
    assert preflight.exit_code == 0
    preflight_payload = json.loads(preflight.output)
    assert preflight_payload["items"][0]["item"]["id"] == item["id"]
    assert preflight_payload["boundary"]["status"] == "passed"

    dependency = runner.invoke(
        app,
        [
            "add-dependency",
            "--source-id",
            item["id"],
            "--target-id",
            "regulation-r-section-12",
        ],
    )
    assert dependency.exit_code == 0

    check = runner.invoke(app, ["check-currency", item["id"]])
    show = runner.invoke(app, ["show-currency", item["id"]])
    assert check.exit_code == 0
    assert show.exit_code == 0
    assert json.loads(check.output)["currency_state"] == "Live"
    assert json.loads(show.output)["currency_state"] == "Live"

    dependencies = runner.invoke(app, ["get-dependencies", item["id"]])
    assert dependencies.exit_code == 0
    assert json.loads(dependencies.output)["dependencies"][0]["target_id"] == "regulation-r-section-12"

    impact = runner.invoke(app, ["impact", "regulation-r-section-12"])
    impact_query = runner.invoke(app, ["impact-query", "regulation-r-section-12"])
    assert impact.exit_code == 0
    assert impact_query.exit_code == 0
    assert json.loads(impact.output)["changed_dependency_id"] == "regulation-r-section-12"
    assert json.loads(impact_query.output)["changed_dependency_id"] == "regulation-r-section-12"

    verified = runner.invoke(
        app,
        ["verify-position", item["id"], "--outcome", "reaffirm", "--by", "Partner A", "--basis", "reviewed memo"],
    )
    assert verified.exit_code == 0
    assert json.loads(verified.output)["verified_by"] == "Partner A"

    pack_dir = tmp_path / "pack"
    audit_pack = runner.invoke(app, ["audit-pack", item["id"], str(pack_dir)])
    assert audit_pack.exit_code == 0
    assert (pack_dir / "manifest.json").exists()


def test_cli_dependency_suggestion_queue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)

    ingest = runner.invoke(
        app,
        [
            "ingest",
            "This position relies on Regulation R section 12.",
            "--source-ref",
            "memo-cli-deps",
            "--kind",
            "position",
            "--source-kind",
            "partner",
        ],
    )
    assert ingest.exit_code == 0
    item = json.loads(ingest.output)

    pending = runner.invoke(app, ["dependency-suggestions", "--item-id", item["id"]])
    assert pending.exit_code == 0
    suggestions = json.loads(pending.output)
    assert suggestions[0]["decision"] == "pending"
    assert suggestions[0]["suggested_edge"]["target_id"] == "regulation-r-section-12"

    confirm = runner.invoke(
        app,
        ["confirm-dependency-suggestion", suggestions[0]["id"], "--by", "Partner A"],
    )
    assert confirm.exit_code == 0
    edge = json.loads(confirm.output)
    assert edge["confidence"] == "human_confirmed"

    confirmed = runner.invoke(app, ["dependency-suggestions", "--item-id", item["id"], "--decision", "confirmed"])
    assert confirmed.exit_code == 0
    assert json.loads(confirmed.output)[0]["decision"] == "confirmed"
