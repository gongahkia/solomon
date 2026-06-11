# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from solomon import __version__
from solomon.api.service import AuthorityChangeRequest, IngestRequest, RecallRequest, SolomonService
from solomon.boundary.kaypoh import probe_kaypoh_client
from solomon.config import get_settings
from solomon.currency.models import KnowledgeKind, SourceKind

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
) -> None:
    results = _service().recall(RecallRequest(query=query, review_mode=review_mode))
    console.print(json.dumps(results, indent=2, sort_keys=True))


@app.command("show-currency")
def show_currency(item_id: str) -> None:
    console.print(json.dumps(_service().evaluate_currency(item_id), indent=2, sort_keys=True))


@app.command("impact-query")
def impact_query(authority_id: str) -> None:
    console.print(json.dumps(_service().impact_query(authority_id), indent=2, sort_keys=True))


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
