# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel


class KaypohImportStatus(BaseModel):
    importable: bool
    repo_path: str
    client_path: str
    detail: str


def _candidate_client_path(kaypoh_repo_path: Path) -> Path:
    return kaypoh_repo_path / "src" / "kaypoh" / "client.py"


def load_kaypoh_client_class(kaypoh_repo_path: Path) -> type[Any]:
    """Load KaypohClient from the sibling checkout without modifying Kaypoh."""
    src_path = kaypoh_repo_path / "src"
    if not _candidate_client_path(kaypoh_repo_path).exists():
        raise ImportError(f"Kaypoh client not found at {_candidate_client_path(kaypoh_repo_path)}")
    src_text = str(src_path.resolve())
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    module = importlib.import_module("kaypoh.client")
    client = getattr(module, "KaypohClient", None)
    if client is None:
        raise ImportError("kaypoh.client does not expose KaypohClient")
    return cast(type[Any], client)


def probe_kaypoh_client(kaypoh_repo_path: Path) -> KaypohImportStatus:
    client_path = _candidate_client_path(kaypoh_repo_path)
    try:
        load_kaypoh_client_class(kaypoh_repo_path)
    except Exception as exc:  # pragma: no cover - detail is environment-dependent
        return KaypohImportStatus(
            importable=False,
            repo_path=str(kaypoh_repo_path),
            client_path=str(client_path),
            detail=str(exc),
        )
    return KaypohImportStatus(
        importable=True,
        repo_path=str(kaypoh_repo_path),
        client_path=str(client_path),
        detail="KaypohClient import succeeded",
    )
