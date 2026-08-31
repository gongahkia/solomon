# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from solomon import __version__
from solomon.api.service import (
    CandidateClaimPromotionRequest,
    DocumentSourceRequest,
    IngestRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.cli.main import app
from solomon.config import get_settings
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.operations.models import OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.sources.models import DocumentSourceKind

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


def test_cli_consistency_check_and_dry_run_repair_are_stable_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_cli_store(monkeypatch, tmp_path)

    checked = runner.invoke(
        app,
        ["consistency", "check", "--matter-id", "matter-a", "--client-id", "client-a", "--format", "json"],
    )
    planned = runner.invoke(app, ["consistency", "repair", "--matter-id", "matter-a", "--client-id", "client-a"])

    assert checked.exit_code == 0, checked.output
    assert planned.exit_code == 0, planned.output
    assert json.loads(checked.output)["scope"] == {"client_id": "client-a", "matter_id": "matter-a", "tenant_id": None}
    assert json.loads(planned.output)["actions"] == []


def test_cli_consistency_operations_and_manual_retry_emit_stable_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_cli_store(monkeypatch, tmp_path)
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    operation, _ = service.operation_store.create(
        OperationRecord(
            operation_type=OperationType.SUGGESTION_GENERATION,
            scope=OperationScope(matter_id="matter-a", client_id="client-a"),
            actor_id="system:test",
            authorization_context={"service_access": "curate"},
            correlation_id="cli-operation-retry",
            idempotency_key="cli-operation-retry",
            target_resource_id="missing-item",
            requested_transition="suggestions_generated",
        )
    )
    assert service.operation_store.claim_next(worker_id="worker-a") is not None
    terminal = service.operation_store.retry(
        operation.id,
        worker_id="worker-a",
        retry_at=operation.created_at,
        failure_category="injectedoperationfailure",
        diagnostic="InjectedOperationFailure",
        maximum_attempts=1,
    )
    assert terminal.status is OperationStatus.TERMINAL_FAILED

    listed = runner.invoke(
        app,
        ["consistency", "operations", "--matter-id", "matter-a", "--client-id", "client-a", "--format", "json"],
    )
    retried = runner.invoke(
        app,
        [
            "consistency",
            "retry",
            operation.id,
            "--by",
            "operator-a",
            "--matter-id",
            "matter-a",
            "--client-id",
            "client-a",
        ],
    )

    assert listed.exit_code == retried.exit_code == 0
    assert json.loads(listed.output)[0]["status"] == "terminal_failed"
    assert json.loads(retried.output)["status"] == "queued"


def test_cli_mcp_serve_dispatches_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("solomon.cli.main.run_stdio_server", lambda: calls.append("stdio"))

    result = runner.invoke(app, ["mcp", "serve"])

    assert result.exit_code == 0
    assert calls == ["stdio"]


def test_cli_mcp_serve_loads_selected_jurisdiction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)
    calls: list[object] = []
    monkeypatch.setattr("solomon.cli.main.run_stdio_server", lambda service: calls.append(service))

    result = runner.invoke(app, ["mcp", "serve", "--jurisdiction", "uk"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert isinstance(calls[0], SolomonService)
    assert calls[0].boundary.policy.default_source_jurisdiction == "UK"
    assert calls[0].boundary.policy.default_destination_jurisdiction == "UK"


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
        ["migrate"],
        ["worker"],
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
        ["assert-dependency"],
        ["dependency-assertion"],
        ["dependency-assertions"],
        ["decide-dependency-assertion"],
        ["withdraw-dependency-assertion"],
        ["verify-position"],
        ["why"],
        ["audit-pack"],
        ["backup"],
        ["restore"],
        ["recovery-drill"],
        ["deployment", "preflight"],
        ["deployment", "init"],
        ["deployment", "compatibility"],
        ["deployment", "maintenance"],
        ["deployment", "release-maintenance"],
        ["deployment", "backup"],
        ["deployment", "backup-inspect"],
        ["deployment", "restore-plan"],
        ["deployment", "restore"],
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


def test_cli_deployment_commands_emit_stable_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)
    SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    initialized = runner.invoke(app, ["deployment", "init", "--owner", "operator-a"])
    preflight = runner.invoke(app, ["deployment", "preflight", "--require-initialized", "--format", "json"])
    compatibility = runner.invoke(app, ["deployment", "compatibility"])
    maintenance = runner.invoke(app, ["deployment", "maintenance", "--format", "json"])

    assert initialized.exit_code == preflight.exit_code == compatibility.exit_code == maintenance.exit_code == 0
    assert json.loads(initialized.output)["created"] is True
    assert json.loads(preflight.output)["ready"] is True
    assert json.loads(compatibility.output)["writable"] is True
    assert json.loads(maintenance.output) == {"active": False, "maintenance": None}


def test_cli_backup_restore_and_recovery_drill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)
    monkeypatch.setenv("SOLOMON_BACKUP_PASSPHRASE", "cli-backup-passphrase")
    SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal").ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="CLI recovery position",
            source_kind=SourceKind.PARTNER,
            source_ref="cli-backup-memo",
        )
    )
    archive = tmp_path / "backup.enc"

    backed_up = runner.invoke(app, ["backup", str(archive)])
    assert backed_up.exit_code == 0, backed_up.output
    assert "cli-backup-passphrase" not in backed_up.output

    restored_root = tmp_path / "restored"
    restored = runner.invoke(app, ["restore", str(archive), str(restored_root)])
    assert restored.exit_code == 0, restored.output
    assert (restored_root / "data" / "solomon.sqlite3").is_file()

    drill = runner.invoke(app, ["recovery-drill", str(archive)])
    assert drill.exit_code == 0, drill.output
    assert json.loads(drill.output)["knowledge_items"] == 1


def test_cli_migrate_and_worker_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)

    migrated = runner.invoke(app, ["migrate"])
    worker = runner.invoke(app, ["worker", "--once"])

    assert migrated.exit_code == 0, migrated.output
    assert json.loads(migrated.output) == {"backend": "sqlite", "status": "applied"}
    assert worker.exit_code == 0, worker.output
    assert json.loads(worker.output) == {
        "operations": {"attempted": 0, "completed": 0, "failed": 0, "retrying": 0, "terminal": 0},
        "source_sync": {"attempted": 0, "failed": 0, "skipped": 0, "succeeded": 0},
    }


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


def test_cli_console_serve_loads_selected_jurisdiction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)
    calls: list[dict[str, object]] = []

    def run(application: object, **kwargs: object) -> None:
        calls.append({"application": application, **kwargs})

    monkeypatch.setattr("uvicorn.run", run)

    result = runner.invoke(app, ["console", "serve", "--jurisdiction", "eu"])

    assert result.exit_code == 0
    application = calls[0]["application"]
    assert isinstance(application, FastAPI)
    service = application.state.service
    assert isinstance(service, SolomonService)
    assert service.boundary.policy.default_source_jurisdiction == "EU"
    assert service.boundary.policy.default_destination_jurisdiction == "EU"


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


def test_cli_governed_dependency_assertion_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli_store(monkeypatch, tmp_path)
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source = service.register_document_source(
        DocumentSourceRequest(
            source_id="cli-documents",
            name="CLI documents",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref="/cli-documents",
        )
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="cli-assertion-memo",
            filename="cli-assertion-memo.txt",
            mime_type="text/plain",
            content="We rely on Regulation R section 12. The conclusion applies to the operating rule.",
        ),
    )
    item = service.promote_candidate_claim(
        candidates[0].id,
        CandidateClaimPromotionRequest(
            by="curator-a",
            kind=KnowledgeKind.POSITION,
            source_kind=SourceKind.MATTER_DOC,
            matter_id="matter-a",
            client_id="client-a",
        ),
    )
    service.register_authority_source(
        AuthoritySource(
            id="cli-gazette",
            name="CLI official gazette",
            kind=AuthoritySourceKind.FEED,
            root_ref="https://gazette.example.test/cli",
        )
    )
    quote = "We rely on Regulation R section 12."
    request_path = tmp_path / "assertion.json"
    request_path.write_text(
        json.dumps(
            {
                "item_id": item.id,
                "source_document_id": document.id,
                "source_document_version": document.version,
                "target_kind": "external_authority",
                "authority_source_id": "cli-gazette",
                "authority_identifier": "SG-R-12",
                "assertion_type": "normative_policy",
                "evidence_kind": "quote",
                "quote": quote,
                "quote_start": 0,
                "quote_end": len(quote),
                "rationale": "CLI assertion lifecycle proof",
                "created_by": "curator-a",
                "idempotency_key": "cli-quote",
            }
        ),
        encoding="utf-8",
    )
    created = runner.invoke(app, ["assert-dependency", "--json", str(request_path)])
    assert created.exit_code == 0, created.output
    quote_assertion = json.loads(created.output)

    inspected = runner.invoke(
        app,
        ["dependency-assertion", quote_assertion["id"], "--matter-id", "matter-a", "--client-id", "client-a"],
    )
    listed = runner.invoke(app, ["dependency-assertions", "--item-id", item.id, "--state", "pending"])
    confirmed = runner.invoke(
        app,
        [
            "decide-dependency-assertion",
            quote_assertion["id"],
            "--by",
            "reviewer-a",
            "--decision",
            "confirmed",
            "--expected-state-version",
            "1",
        ],
    )
    assert inspected.exit_code == 0, inspected.output
    assert listed.exit_code == 0, listed.output
    assert confirmed.exit_code == 0, confirmed.output
    assert json.loads(confirmed.output)["source_suggestion_id"] == quote_assertion["id"]

    commentary = runner.invoke(
        app,
        [
            "assert-dependency",
            "--item-id",
            item.id,
            "--source-document-id",
            document.id,
            "--source-document-version",
            str(document.version),
            "--authority-source-id",
            "cli-gazette",
            "--authority-identifier",
            "SG-R-13",
            "--assertion-type",
            "procedural",
            "--evidence-kind",
            "commentary",
            "--commentary",
            "The curator records a procedural dependency without claiming a quotation.",
            "--rationale",
            "CLI commentary lifecycle proof",
            "--created-by",
            "curator-a",
            "--idempotency-key",
            "cli-commentary",
        ],
    )
    assert commentary.exit_code == 0, commentary.output
    commentary_assertion = json.loads(commentary.output)
    deferred = runner.invoke(
        app,
        [
            "decide-dependency-assertion",
            commentary_assertion["id"],
            "--by",
            "reviewer-a",
            "--decision",
            "deferred",
            "--reason",
            "needs review",
        ],
    )
    withdrawn = runner.invoke(
        app,
        [
            "withdraw-dependency-assertion",
            commentary_assertion["id"],
            "--by",
            "curator-a",
            "--reason",
            "withdrawn before confirmation",
            "--expected-state-version",
            "2",
        ],
    )
    assert deferred.exit_code == 0, deferred.output
    assert withdrawn.exit_code == 0, withdrawn.output
    assert json.loads(withdrawn.output)["decision"] == "withdrawn"
