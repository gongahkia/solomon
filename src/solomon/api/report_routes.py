# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from solomon.api.service import SolomonService
from solomon.currency.report import CurrencyMovementReport, ReportScopeKind, render_currency_report_pdf


def register_currency_report_routes(
    app: FastAPI,
    active_service: Callable[[Request], SolomonService],
) -> None:
    @app.get("/currency/report")
    def currency_report(
        request: Request,
        period_start: str,
        period_end: str,
        scope: Literal["firm", "practice_area", "matter"] = "firm",
        practice_area: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        report = _currency_report_from_query(
            active_service(request),
            period_start=period_start,
            period_end=period_end,
            scope=scope,
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )
        return report.model_dump(mode="json")

    @app.get("/currency/report/export")
    def currency_report_export(
        request: Request,
        period_start: str,
        period_end: str,
        scope: Literal["firm", "practice_area", "matter"] = "firm",
        practice_area: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        format: Literal["json", "pdf", "pack"] = "json",
    ) -> Response:
        service = active_service(request)
        report = _currency_report_from_query(
            service,
            period_start=period_start,
            period_end=period_end,
            scope=scope,
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )
        if format == "pdf":
            return Response(
                content=render_currency_report_pdf(report),
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="currency-report.pdf"'},
            )
        if format == "pack":
            with TemporaryDirectory(prefix="solomon-currency-report-") as temp_dir:
                pack_dir = service.export_currency_report_pack(Path(temp_dir), report)
                manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
                journal_jsonl = (pack_dir / str(manifest["journal_file"])).read_text(encoding="utf-8")
            return JSONResponse(
                content={
                    "schema": "solomon.currency_report_pack.v1",
                    "report": report.model_dump(mode="json"),
                    "manifest": manifest,
                    "journal_jsonl": journal_jsonl,
                },
                headers={"Content-Disposition": 'attachment; filename="currency-report-pack.json"'},
            )
        return JSONResponse(
            content=report.model_dump(mode="json"),
            headers={"Content-Disposition": 'attachment; filename="currency-report.json"'},
        )


def _currency_report_from_query(
    service: SolomonService,
    *,
    period_start: str,
    period_end: str,
    scope: ReportScopeKind,
    practice_area: str | None,
    matter_id: str | None,
    client_id: str | None,
) -> CurrencyMovementReport:
    try:
        start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
        return service.currency_report(
            period_start=start,
            period_end=end,
            scope=scope,
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
