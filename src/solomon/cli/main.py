# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console

from solomon import __version__
from solomon.api.app import _model_router_from_settings
from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    IngestRequest,
    RecallRequest,
    ReferenceExtractionRequest,
    SolomonService,
    StalenessPredictionRequest,
    VerificationRequest,
)
from solomon.backup import BackupError, create_encrypted_backup, restore_encrypted_backup, run_recovery_drill
from solomon.boundary.solomon import SolomonBoundary, probe_boundary_client
from solomon.config import (
    boundary_policy_from_settings,
    credence_policy_from_settings,
    get_settings,
    settings_with_jurisdiction,
    verification_policy_from_settings,
)
from solomon.currency.contradiction import ConclusionPolarity
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.currency.prediction import load_pending_amendments
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.graph.suggestions import SuggestionDecision
from solomon.graph.visualization import GraphFormat
from solomon.mcp.server import run_sse_server, run_stdio_server, run_streamable_http_server
from solomon.mcp.tools import SolomonMCPRuntime
from solomon.telemetry import telemetry_from_settings
from solomon.worker import sync_enabled_filesystem_sources


def _example(command: str) -> str:
    return f"Example:\n  {command}"


app = typer.Typer(
    help="Solomon command-line interface.",
    epilog=_example("uv run solomon preflight \"structure X regulation\""),
)
mcp_app = typer.Typer(help="Run Solomon MCP transports.", epilog=_example("uv run solomon mcp serve"))
console_app = typer.Typer(
    help="Run Solomon curator console.",
    epilog=_example("uv run solomon console serve --host 127.0.0.1 --port 8150"),
)
app.add_typer(mcp_app, name="mcp")
app.add_typer(console_app, name="console")
console = Console()


def _print_json(payload: object, *, sort_keys: bool = False) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=sort_keys))


def _version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Print Solomon version."),
    ] = False,
) -> None:
    _ = version


@app.command(epilog=_example("uv run solomon diagnostics"))
def diagnostics() -> None:
    """Print local Solomon diagnostics."""
    settings = get_settings()
    payload = {
        "version": __version__,
        "settings": settings.public_diagnostics(),
        "boundary": probe_boundary_client(settings.boundary_engine_path).model_dump(),
    }
    _print_json(payload, sort_keys=True)


@app.command(epilog=_example("uv run solomon health"))
def health() -> None:
    """Print MCP-aligned local health."""
    settings = get_settings()
    service = _service()
    payload = {
        "version": __version__,
        "store": {"ok": True, "item_count": len(service.store.get_many())},
        "journal": service.audit.verify().model_dump(mode="json"),
        "boundary": probe_boundary_client(settings.boundary_engine_path).model_dump(mode="json"),
    }
    _print_json(payload, sort_keys=True)


@app.command("migrate", epilog=_example("uv run solomon migrate"))
def migrate() -> None:
    """Apply durable storage migrations and exit."""
    settings = get_settings()
    _ = _service()
    backend = "postgres" if settings.database_url.startswith(("postgres://", "postgresql://")) else "sqlite"
    _print_json({"status": "applied", "backend": backend}, sort_keys=True)


@app.command("worker", epilog=_example("uv run solomon worker --once"))
def worker(
    once: Annotated[bool, typer.Option("--once", help="Run one source-sync cycle and exit.")] = False,
    interval_seconds: Annotated[
        int | None, typer.Option("--interval-seconds", min=5, help="Seconds between source-sync cycles.")
    ] = None,
    source_limit: Annotated[
        int | None, typer.Option("--source-limit", min=1, help="Maximum sources per cycle.")
    ] = None,
) -> None:
    """Synchronize enabled filesystem document sources."""
    settings = get_settings()
    service = _service()
    interval = interval_seconds or settings.worker_source_sync_interval_seconds
    limit = source_limit or settings.worker_source_sync_limit
    while True:
        _print_json(sync_enabled_filesystem_sources(service, limit=limit).model_dump(), sort_keys=True)
        if once:
            return
        time.sleep(interval)


@mcp_app.command("serve", epilog=_example("uv run solomon mcp serve --http --host 127.0.0.1 --port 8141"))
def mcp_serve(
    http: Annotated[bool, typer.Option("--http", help="Serve Streamable HTTP MCP instead of stdio.")] = False,
    sse: Annotated[bool, typer.Option("--sse", help="Serve legacy SSE MCP instead of stdio.")] = False,
    host: Annotated[str, typer.Option("--host", help="HTTP/SSE bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="HTTP/SSE bind port.")] = 8141,
    jurisdiction: Annotated[
        str | None, typer.Option("--jurisdiction", help="Boundary profile: sg, my, uk, or eu.")
    ] = None,
) -> None:
    """Serve Solomon as an MCP server."""
    if http and sse:
        raise typer.BadParameter("--http and --sse are mutually exclusive")
    if jurisdiction is not None:
        service = _service(jurisdiction=jurisdiction)
        if http:
            run_streamable_http_server(service, host=host, port=port)
            return
        if sse:
            run_sse_server(service, host=host, port=port)
            return
        run_stdio_server(service)
        return
    if http:
        run_streamable_http_server(host=host, port=port)
        return
    if sse:
        run_sse_server(host=host, port=port)
        return
    run_stdio_server()


@console_app.command(
    "serve",
    epilog=_example("uv run solomon console serve --host 127.0.0.1 --port 8150"),
)
def console_serve(
    host: Annotated[str, typer.Option("--host", help="Console bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Console bind port.")] = 8150,
    reload: Annotated[bool, typer.Option("--reload", help="Reload console server on source changes.")] = False,
    jurisdiction: Annotated[
        str | None, typer.Option("--jurisdiction", help="Boundary profile: sg, my, uk, or eu.")
    ] = None,
) -> None:
    """Serve the Solomon curator console."""
    import uvicorn

    if jurisdiction is not None:
        if reload:
            raise typer.BadParameter(
                "--jurisdiction cannot be combined with --reload; use SOLOMON_JURISDICTION instead"
            )
        from solomon.console.app import create_console_app

        uvicorn.run(
            create_console_app(settings=settings_with_jurisdiction(get_settings(), jurisdiction)),
            host=host,
            port=port,
            reload=False,
        )
        return
    uvicorn.run(
        "solomon.console.app:create_console_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


def _service(*, jurisdiction: str | None = None) -> SolomonService:
    settings = get_settings()
    return SolomonService(
        data_dir=settings.data_dir,
        journal_dir=settings.journal_dir,
        attestation_key=settings.verification_attestation_key,
        verification_policy=verification_policy_from_settings(settings),
        verification_policy_version=settings.verification_policy_version,
        credence_policy=credence_policy_from_settings(settings),
        credence_policy_version=settings.credence_policy_version,
        telemetry=telemetry_from_settings(
            enabled=settings.telemetry_enabled,
            service_name=settings.telemetry_service_name,
            otlp_endpoint=settings.telemetry_otlp_endpoint,
        ),
        boundary=SolomonBoundary(policy=boundary_policy_from_settings(settings, jurisdiction=jurisdiction)),
    )


def _backup_passphrase() -> str:
    passphrase = os.environ.get("SOLOMON_BACKUP_PASSPHRASE")
    if not passphrase:
        raise typer.BadParameter("set SOLOMON_BACKUP_PASSPHRASE")
    return passphrase


def _require_sqlite_backup_target() -> None:
    database_url = get_settings().database_url
    if database_url.startswith(("postgres://", "postgresql://")):
        raise typer.BadParameter("backup commands currently support SQLite deployments only")


@app.command("backup", epilog=_example("SOLOMON_BACKUP_PASSPHRASE=... uv run solomon backup ./solomon-backup.enc"))
def backup(destination: Annotated[Path, typer.Argument(help="New encrypted backup archive path.")]) -> None:
    """Create an encrypted backup of local durable data and journal files."""
    _require_sqlite_backup_target()
    settings = get_settings()
    try:
        result = create_encrypted_backup(
            data_dir=settings.data_dir,
            journal_dir=settings.journal_dir,
            destination=destination,
            passphrase=_backup_passphrase(),
        )
    except BackupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_json(result.model_dump(mode="json"), sort_keys=True)


@app.command(
    "restore",
    epilog=_example("SOLOMON_BACKUP_PASSPHRASE=... uv run solomon restore ./solomon-backup.enc ./restored-deployment"),
)
def restore(
    archive: Annotated[Path, typer.Argument(help="Encrypted backup archive path.")],
    destination: Annotated[Path, typer.Argument(help="New empty deployment-root path.")],
) -> None:
    """Restore an encrypted backup into a fresh deployment root."""
    try:
        result = restore_encrypted_backup(archive, destination, passphrase=_backup_passphrase())
    except BackupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_json(result.model_dump(mode="json"), sort_keys=True)


@app.command(
    "recovery-drill",
    epilog=_example("SOLOMON_BACKUP_PASSPHRASE=... uv run solomon recovery-drill ./solomon-backup.enc"),
)
def recovery_drill(archive: Annotated[Path, typer.Argument(help="Encrypted backup archive path.")]) -> None:
    """Restore and validate an encrypted backup in a temporary fresh deployment."""
    try:
        report = run_recovery_drill(archive, passphrase=_backup_passphrase())
    except BackupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print_json(report.model_dump(mode="json"), sort_keys=True)


@app.command(
    help="Boundary-check and ingest new firm knowledge.",
    epilog=_example('uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1'),
)
def ingest(
    content: Annotated[str, typer.Argument(help="Knowledge content to ingest.")],
    source_ref: Annotated[str, typer.Option("--source-ref", help="Source reference.")],
    kind: Annotated[KnowledgeKind, typer.Option("--kind")] = KnowledgeKind.NOTE,
    source_kind: Annotated[SourceKind, typer.Option("--source-kind")] = SourceKind.ASSOCIATE,
    conclusion: Annotated[str | None, typer.Option("--conclusion", help="Structured conclusion text.")] = None,
    conclusion_polarity: Annotated[ConclusionPolarity | None, typer.Option("--conclusion-polarity")] = None,
    jurisdiction: Annotated[
        str | None, typer.Option("--jurisdiction", help="Boundary profile: sg, my, uk, or eu.")
    ] = None,
) -> None:
    item = _service(jurisdiction=jurisdiction).ingest(
        IngestRequest(
            kind=kind,
            content=content,
            source_kind=source_kind,
            source_ref=source_ref,
            conclusion=conclusion,
            conclusion_polarity=conclusion_polarity,
        )
    )
    _print_json(item.model_dump(mode="json"))


@app.command(
    help="Recall live knowledge by query.",
    epilog=_example('uv run solomon recall "structure X regulation" --review-mode'),
)
def recall(
    query: Annotated[str, typer.Argument(help="Question or search query.")],
    review_mode: Annotated[bool, typer.Option("--review-mode")] = False,
    max_context_tokens: Annotated[
        int | None,
        typer.Option("--max-context-tokens", min=1, help="Maximum estimated context tokens to assemble."),
    ] = None,
) -> None:
    results = _service().recall(
        RecallRequest(query=query, review_mode=review_mode, max_context_tokens=max_context_tokens)
    )
    _print_json(results, sort_keys=True)


@app.command(
    "preflight",
    epilog=_example('uv run solomon preflight "structure X regulation" --matter-id matter-a'),
)
def preflight(
    query: Annotated[str, typer.Argument(help="Question or search query.")],
    matter_id: Annotated[str | None, typer.Option("--matter-id", help="Restrict to a matter scope.")] = None,
    client_id: Annotated[str | None, typer.Option("--client-id", help="Restrict to a client scope.")] = None,
    max_items: Annotated[int, typer.Option("--max-items", min=1, help="Maximum current items to return.")] = 5,
    max_context_tokens: Annotated[
        int | None,
        typer.Option("--max-context-tokens", min=1, help="Maximum estimated context tokens to assemble."),
    ] = None,
) -> None:
    """Return MCP-shaped current context safe for prompt injection."""
    result = SolomonMCPRuntime(_service()).preflight_context(
        query=query,
        matter_id=matter_id,
        client_id=client_id,
        max_items=max_items,
        max_context_tokens=max_context_tokens,
    )
    _print_json(result, sort_keys=True)


def _print_currency(item_id: str) -> None:
    _print_json(_service().evaluate_currency(item_id), sort_keys=True)


@app.command(
    "check-currency",
    epilog=_example("uv run solomon check-currency 019ec64a-83dd-71cc-9422-7b6ec405cd43"),
)
def check_currency(item_id: Annotated[str, typer.Argument(help="Knowledge item id.")]) -> None:
    """Check whether a knowledge item is live, stale, superseded, or retired."""
    _print_currency(item_id)


@app.command("show-currency", hidden=True)
def show_currency(item_id: str) -> None:
    _print_currency(item_id)


def _print_impact(authority_id: str) -> None:
    _print_json(_service().impact_query(authority_id), sort_keys=True)


@app.command("impact", epilog=_example("uv run solomon impact regulation-r-section-12"))
def impact(authority_id: Annotated[str, typer.Argument(help="External authority id.")]) -> None:
    """Return internal items affected by an external authority."""
    _print_impact(authority_id)


@app.command("impact-query", hidden=True)
def impact_query(authority_id: str) -> None:
    _print_impact(authority_id)


@app.command(
    "get-dependencies",
    epilog=_example("uv run solomon get-dependencies 019ec64a-83dd-71cc-9422-7b6ec405cd43"),
)
def get_dependencies(item_id: Annotated[str, typer.Argument(help="Knowledge item id.")]) -> None:
    """Return upstream and downstream dependency edges for a knowledge item."""
    trace = _service().why(item_id)
    _print_json(
        {
            "item_id": item_id,
            "dependencies": trace.dependencies,
            "dependents": trace.dependents,
        },
        sort_keys=True,
    )


@app.command(
    "dependency-graph",
    help="Render dependency graph as Mermaid or DOT.",
    epilog=_example("uv run solomon dependency-graph --format mermaid --matter-id matter-a"),
)
def dependency_graph(
    output_format: Annotated[str, typer.Option("--format", help="Graph format: mermaid or dot.")] = "mermaid",
    matter_id: Annotated[str | None, typer.Option("--matter-id", help="Restrict to a matter scope.")] = None,
    client_id: Annotated[str | None, typer.Option("--client-id", help="Restrict to a client scope.")] = None,
) -> None:
    if output_format not in {"mermaid", "dot"}:
        raise typer.BadParameter("format must be mermaid or dot")
    console.print(
        _service().dependency_graph(
            output_format=cast(GraphFormat, output_format),
            matter_id=matter_id,
            client_id=client_id,
        )
    )


@app.command(
    "extract-refs",
    help="Extract references from knowledge text.",
    epilog=_example('uv run solomon extract-refs "This relies on Regulation R section 12."'),
)
def extract_refs(content: Annotated[str, typer.Argument(help="Knowledge text to scan.")]) -> None:
    extraction = _service().extract_references(ReferenceExtractionRequest(content=content))
    _print_json(extraction.model_dump(mode="json"))


@app.command(
    "predict-stale",
    help="Predict staleness risk from a pending-amendment feed.",
    epilog=_example("uv run solomon predict-stale examples/pending-amendments.json --lookahead-days 180"),
)
def predict_stale(
    pending_feed: Annotated[Path, typer.Argument(help="JSON or CSV feed of pending authority amendments.")],
    lookahead_days: Annotated[int, typer.Option("--lookahead-days", min=1)] = 180,
) -> None:
    report = _service().predict_staleness(
        StalenessPredictionRequest(
            pending_amendments=load_pending_amendments(pending_feed),
            lookahead_days=lookahead_days,
        )
    )
    _print_json(report.model_dump(mode="json"))


@app.command(
    "register-authority-change",
    help="Register an external authority version change and propagate stale state.",
    epilog=_example(
        "uv run solomon register-authority-change regulation-r-section-12 "
        "--new-version 2026-amendment --changed-at 2026-01-01T00:00:00+00:00"
    ),
)
def register_authority_change(
    authority_id: Annotated[str, typer.Argument(help="External authority id.")],
    new_version: Annotated[str, typer.Option("--new-version", help="New authority version.")],
    changed_at: Annotated[str, typer.Option("--changed-at", help="ISO-8601 change timestamp.")],
) -> None:
    result = _service().register_authority_change(
        authority_id,
        AuthorityChangeRequest(new_version=new_version, changed_at=changed_at),
    )
    _print_json(result, sort_keys=True)


@app.command(
    "add-dependency",
    help="Add a dependency edge from a knowledge item to an authority or item.",
    epilog=_example(
        "uv run solomon add-dependency --source-id item-1 --target-id regulation-r-section-12 "
        "--edge-type internal_depends_on_external"
    ),
)
def add_dependency(
    source_id: Annotated[str, typer.Option("--source-id", help="Knowledge item id.")],
    target_id: Annotated[str, typer.Option("--target-id", help="Authority or item id.")],
    edge_type: Annotated[EdgeType, typer.Option("--edge-type")] = EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
    target_kind: Annotated[str, typer.Option("--target-kind")] = "external_authority",
    confidence: Annotated[EdgeConfidence, typer.Option("--confidence")] = EdgeConfidence.HUMAN_ASSERTED,
) -> None:
    edge = _service().add_dependency(
        DependencyRequest(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            target_kind=target_kind,
            confidence=confidence,
        )
    )
    _print_json(edge.model_dump(mode="json"))


@app.command(
    "suggest-dependencies",
    help="Create dependency suggestions for one knowledge item.",
    epilog=_example("uv run solomon suggest-dependencies item-1"),
)
def suggest_dependencies(
    item_id: Annotated[str, typer.Argument(help="Knowledge item id.")],
    llm: Annotated[bool, typer.Option("--llm", help="Use optional sanitized LLM extraction.")] = False,
) -> None:
    settings = get_settings()
    suggestions = _service().suggest_dependencies(
        DependencySuggestionRequest(item_id=item_id, use_llm=llm),
        router=_model_router_from_settings(settings) if llm else None,
    )
    _print_json([suggestion.model_dump(mode="json") for suggestion in suggestions])


@app.command(
    "dependency-suggestions",
    help="List dependency suggestions for review.",
    epilog=_example("uv run solomon dependency-suggestions --decision pending --limit 20"),
)
def dependency_suggestions(
    item_id: Annotated[str | None, typer.Option("--item-id", help="Restrict to one knowledge item.")] = None,
    decision: Annotated[SuggestionDecision | None, typer.Option("--decision")] = SuggestionDecision.PENDING,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
) -> None:
    suggestions = _service().dependency_suggestions(item_id=item_id, decision=decision, limit=limit)
    _print_json([suggestion.model_dump(mode="json") for suggestion in suggestions])


@app.command(
    "confirm-dependency-suggestion",
    help="Confirm one dependency suggestion.",
    epilog=_example("uv run solomon confirm-dependency-suggestion suggestion-1 --by PartnerA"),
)
def confirm_dependency_suggestion(
    suggestion_id: Annotated[str, typer.Argument(help="Dependency suggestion id.")],
    by: Annotated[str, typer.Option("--by", help="Reviewer identifier.")],
) -> None:
    edge = _service().confirm_dependency_suggestion(
        suggestion_id,
        DependencySuggestionDecisionRequest(by=by),
    )
    _print_json(edge.model_dump(mode="json"))


@app.command(
    "reject-dependency-suggestion",
    help="Reject one dependency suggestion.",
    epilog=_example("uv run solomon reject-dependency-suggestion suggestion-1 --by PartnerA"),
)
def reject_dependency_suggestion(
    suggestion_id: Annotated[str, typer.Argument(help="Dependency suggestion id.")],
    by: Annotated[str, typer.Option("--by", help="Reviewer identifier.")],
) -> None:
    suggestion = _service().reject_dependency_suggestion(
        suggestion_id,
        DependencySuggestionDecisionRequest(by=by),
    )
    _print_json(suggestion.model_dump(mode="json"))


@app.command(
    "verify-position",
    epilog=_example("uv run solomon verify-position item-1 --outcome reaffirm --by PartnerA"),
)
def verify_position(
    item_id: Annotated[str, typer.Argument(help="Knowledge item id.")],
    outcome: Annotated[VerificationOutcome, typer.Option("--outcome")],
    by: Annotated[str, typer.Option("--by", help="Verifier identifier.")],
    successor_id: Annotated[str | None, typer.Option("--successor-id", help="Required for supersede.")] = None,
    basis: Annotated[str | None, typer.Option("--basis", help="Verification rationale or basis.")] = None,
    source_ref: Annotated[str | None, typer.Option("--source-ref", help="Optional evidence source pointer.")] = None,
) -> None:
    """Record a human verification decision with evidence."""
    item = _service().record_verification(
        item_id,
        VerificationRequest(by=by, outcome=outcome, basis=basis, source_ref=source_ref, successor_id=successor_id),
    )
    _print_json(item.model_dump(mode="json"))


@app.command(
    "why",
    help="Print a compact explanation for one knowledge item.",
    epilog=_example("uv run solomon why item-1"),
)
def why(item_id: str) -> None:
    trace = _service().why(item_id)
    console.print(f"{trace.item.id} [{trace.currency['currency_state']}]")
    console.print(f"credence: {trace.credence_tier}")
    console.print(f"source: {trace.provenance['source_ref']}")
    console.print(f"dependencies: {len(trace.dependencies)}")


@app.command(
    "audit-pack",
    epilog=_example("uv run solomon audit-pack item-1 ./audit-pack"),
)
def audit_pack(
    item_id: Annotated[str, typer.Argument(help="Knowledge item id.")],
    destination: Annotated[Path, typer.Argument(help="Destination directory.")],
) -> None:
    """Export audit-pack evidence after validating the selected item."""
    service = _service()
    _ = service.why(item_id)
    console.print(str(service.export_audit_pack(destination)))


@app.command("export-audit-pack", hidden=True)
def export_audit_pack(destination: Annotated[Path, typer.Argument(help="Destination directory.")]) -> None:
    console.print(str(_service().export_audit_pack(destination)))


if __name__ == "__main__":
    app()
