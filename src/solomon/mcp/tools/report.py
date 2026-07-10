# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast

from solomon.currency.report import ReportScopeKind, render_currency_report_pdf
from solomon.mcp.tools.helpers import _error_result, _mcp_log_payload

if TYPE_CHECKING:
    from solomon.mcp.tools.runtime import SolomonMCPRuntime


def currency_report(
    runtime: SolomonMCPRuntime,
    *,
    period_start: str,
    period_end: str,
    scope: str = "firm",
    practice_area: str | None = None,
    matter_id: str | None = None,
    client_id: str | None = None,
    format: str = "json",
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.currency_report", caller_id)
    if limited is not None:
        return limited
    if scope not in {"firm", "practice_area", "matter"}:
        return _error_result(
            "bad_request",
            "unsupported currency report scope",
            retryable=False,
            details={"scope": scope},
        )
    if format not in {"json", "pdf", "pack"}:
        return _error_result(
            "bad_request",
            "unsupported currency report format",
            retryable=False,
            details={"format": format},
        )
    try:
        report = runtime.service.currency_report(
            period_start=datetime.fromisoformat(period_start.replace("Z", "+00:00")),
            period_end=datetime.fromisoformat(period_end.replace("Z", "+00:00")),
            scope=cast(ReportScopeKind, scope),
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )
    except ValueError as exc:
        return _error_result("bad_request", str(exc), retryable=False, details={})
    pack: dict[str, Any] | None = None
    pdf_base64: str | None = None
    if format == "pdf":
        pdf_base64 = base64.b64encode(render_currency_report_pdf(report)).decode("ascii")
    elif format == "pack":
        with TemporaryDirectory(prefix="solomon-mcp-currency-report-") as temp_dir:
            pack_dir = runtime.service.export_currency_report_pack(Path(temp_dir), report)
            manifest = (pack_dir / "manifest.json").read_text(encoding="utf-8")
            report_json = (pack_dir / "currency-report.json").read_text(encoding="utf-8")
        pack = {"manifest_json": manifest, "report_json": report_json}
    entry = runtime.service.audit.append(
        "mcp_call",
        _mcp_log_payload(
            "solomon.currency_report",
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            input_payload={
                "period_start": period_start,
                "period_end": period_end,
                "scope": scope,
                "practice_area": practice_area,
                "format": format,
            },
        ),
    )
    return {
        "schema_id": "solomon.mcp.currency_report.v1",
        "format": format,
        "report": report.model_dump(mode="json"),
        "pack": pack,
        "pdf_base64": pdf_base64,
        "hash_chain": {"entry_hash": entry.entry_hash},
    }
