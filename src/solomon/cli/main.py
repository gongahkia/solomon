# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console

from solomon import __version__
from solomon.api.service import (
    AuthorityChangeRequest,
    DependencyRequest,
    IngestRequest,
    RecallRequest,
    ReferenceExtractionRequest,
    SolomonService,
    StalenessPredictionRequest,
)
from solomon.boundary.kaypoh import probe_kaypoh_client
from solomon.config import get_settings
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.currency.prediction import load_pending_amendments
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.graph.visualization import GraphFormat

app = typer.Typer(help="Solomon command-line interface.")
console = Console()


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
        "kaypoh": probe_kaypoh_client(settings.kaypoh_repo_path).model_dump(),
    }
    console.print(json.dumps(payload, indent=2, sort_keys=True))


def _service() -> SolomonService:
    settings = get_settings()
    return SolomonService(data_dir=settings.data_dir, journal_dir=settings.journal_dir)


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
    console.print(item.model_dump_json(indent=2))


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
    console.print(json.dumps(results, indent=2, sort_keys=True))


@app.command("show-currency")
def show_currency(item_id: str) -> None:
    console.print(json.dumps(_service().evaluate_currency(item_id), indent=2, sort_keys=True))


@app.command("impact-query")
def impact_query(authority_id: str) -> None:
    console.print(json.dumps(_service().impact_query(authority_id), indent=2, sort_keys=True))


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
    console.print(extraction.model_dump_json(indent=2))


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
    console.print(report.model_dump_json(indent=2))


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
    console.print(json.dumps(result, indent=2, sort_keys=True))


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
    console.print(edge.model_dump_json(indent=2))


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
