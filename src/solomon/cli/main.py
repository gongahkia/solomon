# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console

from solomon import __version__
from solomon.boundary.kaypoh import probe_kaypoh_client
from solomon.config import get_settings

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

