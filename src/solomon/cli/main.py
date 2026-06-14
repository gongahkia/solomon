# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
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
)
from solomon.boundary.solomon import probe_boundary_client
from solomon.config import get_settings
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.currency.prediction import load_pending_amendments
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.graph.suggestions import SuggestionDecision
from solomon.graph.visualization import GraphFormat

app = typer.Typer(help="Solomon command-line interface.")
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


@app.command()
def diagnostics() -> None:
    """Print local Solomon diagnostics."""
    settings = get_settings()
    payload = {
        "version": __version__,
        "settings": settings.public_diagnostics(),
        "boundary": probe_boundary_client(settings.boundary_engine_path).model_dump(),
    }
    _print_json(payload, sort_keys=True)


def _service() -> SolomonService:
    settings = get_settings()
    return SolomonService(
        data_dir=settings.data_dir,
        journal_dir=settings.journal_dir,
        attestation_key=settings.verification_attestation_key,
    )


@app.command()
def ingest(
    content: Annotated[str, typer.Argument(help="Knowledge content to ingest.")],
    source_ref: Annotated[str, typer.Option("--source-ref", help="Source reference.")],
    kind: Annotated[KnowledgeKind, typer.Option("--kind")] = KnowledgeKind.NOTE,
    source_kind: Annotated[SourceKind, typer.Option("--source-kind")] = SourceKind.ASSOCIATE,
) -> None:
    item = _service().ingest(
        IngestRequest(kind=kind, content=content, source_kind=source_kind, source_ref=source_ref)
    )
    _print_json(item.model_dump(mode="json"))


@app.command()
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


@app.command("show-currency")
def show_currency(item_id: str) -> None:
    _print_json(_service().evaluate_currency(item_id), sort_keys=True)


@app.command("impact-query")
def impact_query(authority_id: str) -> None:
    _print_json(_service().impact_query(authority_id), sort_keys=True)


@app.command("dependency-graph")
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


@app.command("extract-refs")
def extract_refs(content: Annotated[str, typer.Argument(help="Knowledge text to scan.")]) -> None:
    extraction = _service().extract_references(ReferenceExtractionRequest(content=content))
    _print_json(extraction.model_dump(mode="json"))


@app.command("predict-stale")
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


@app.command("register-authority-change")
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


@app.command("add-dependency")
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


@app.command("suggest-dependencies")
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


@app.command("dependency-suggestions")
def dependency_suggestions(
    item_id: Annotated[str | None, typer.Option("--item-id", help="Restrict to one knowledge item.")] = None,
    decision: Annotated[SuggestionDecision | None, typer.Option("--decision")] = SuggestionDecision.PENDING,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
) -> None:
    suggestions = _service().dependency_suggestions(item_id=item_id, decision=decision, limit=limit)
    _print_json([suggestion.model_dump(mode="json") for suggestion in suggestions])


@app.command("confirm-dependency-suggestion")
def confirm_dependency_suggestion(
    suggestion_id: Annotated[str, typer.Argument(help="Dependency suggestion id.")],
    by: Annotated[str, typer.Option("--by", help="Reviewer identifier.")],
) -> None:
    edge = _service().confirm_dependency_suggestion(
        suggestion_id,
        DependencySuggestionDecisionRequest(by=by),
    )
    _print_json(edge.model_dump(mode="json"))


@app.command("reject-dependency-suggestion")
def reject_dependency_suggestion(
    suggestion_id: Annotated[str, typer.Argument(help="Dependency suggestion id.")],
    by: Annotated[str, typer.Option("--by", help="Reviewer identifier.")],
) -> None:
    suggestion = _service().reject_dependency_suggestion(
        suggestion_id,
        DependencySuggestionDecisionRequest(by=by),
    )
    _print_json(suggestion.model_dump(mode="json"))


@app.command("why")
def why(item_id: str) -> None:
    trace = _service().why(item_id)
    console.print(f"{trace.item.id} [{trace.currency['currency_state']}]")
    console.print(f"credence: {trace.credence_tier}")
    console.print(f"source: {trace.provenance['source_ref']}")
    console.print(f"dependencies: {len(trace.dependencies)}")


@app.command("export-audit-pack")
def export_audit_pack(destination: Annotated[Path, typer.Argument(help="Destination directory.")]) -> None:
    console.print(str(_service().export_audit_pack(destination)))


if __name__ == "__main__":
    app()
