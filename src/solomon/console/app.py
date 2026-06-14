# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from solomon.api.service import DependencySuggestionDecisionRequest, PinRequest, SolomonService, VerificationRequest
from solomon.config import Settings, get_settings
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import CredenceTier, CurrencyState, KnowledgeItem, VerifiedState
from solomon.errors import SolomonError
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision

DEFAULT_DATABASE_URL = str(Settings.model_fields["database_url"].default)
PACKAGE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
STATIC_DIR = PACKAGE_DIR / "static"


def create_console_app(*, settings: Settings | None = None, service: SolomonService | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_service = service or SolomonService(
        data_dir=resolved_settings.data_dir,
        journal_dir=resolved_settings.journal_dir,
        attestation_key=resolved_settings.verification_attestation_key,
        database_url=_service_database_url(resolved_settings),
    )
    app = FastAPI(title="Solomon Console")
    app.state.service = resolved_service
    app.mount("/console/static", StaticFiles(directory=str(STATIC_DIR)), name="console-static")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/console/verification")

    @app.get("/console", include_in_schema=False)
    def console_root() -> RedirectResponse:
        return RedirectResponse(url="/console/verification")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/console/verification")
    def verification(request: Request, item_id: str | None = None) -> Response:
        return _render_verification(request, resolved_service, item_id=item_id)

    @app.get("/console/dependencies")
    def dependencies(
        request: Request,
        decision: str = "pending",
        item_id: str | None = None,
        authority_id: str | None = None,
        depth: int = 1,
    ) -> Response:
        return _render_dependencies(
            request,
            resolved_service,
            decision=decision,
            item_id=item_id,
            authority_id=authority_id,
            depth=depth,
        )

    @app.get("/console/verification/items")
    def verification_items(request: Request) -> Response:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/verification_list.html",
            {"items": _review_rows(resolved_service)},
        )

    @app.get("/console/verification/items/{item_id}")
    def verification_item(request: Request, item_id: str) -> Response:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/verification_preview.html",
            _preview_context(request, resolved_service, item_id=item_id),
        )

    @app.post("/console/verification/items/{item_id}/decision")
    async def verification_decision(request: Request, item_id: str) -> Response:
        form = await request.form()
        decision = str(form.get("decision") or "")
        partner_id = str(form.get("partner_id") or "").strip()
        evidence_ref = str(form.get("evidence_ref") or "").strip()
        successor_id = str(form.get("successor_id") or "").strip() or None
        error = _validate_decision_form(decision, partner_id, evidence_ref, successor_id)
        if error is None:
            try:
                _apply_decision(
                    resolved_service,
                    item_id=item_id,
                    decision=decision,
                    partner_id=partner_id,
                    evidence_ref=evidence_ref,
                    successor_id=successor_id,
                )
            except (SolomonError, ValueError) as exc:
                error = str(exc)
        status_code = 200 if error is None else 400
        return TEMPLATES.TemplateResponse(
            request,
            "partials/verification_preview.html",
            _preview_context(request, resolved_service, item_id=item_id, error=error),
            status_code=status_code,
        )

    @app.post("/console/dependencies/suggestions/{suggestion_id}/confirm")
    async def confirm_dependency(request: Request, suggestion_id: str) -> Response:
        form = await request.form()
        reviewer_id = str(form.get("reviewer_id") or "").strip()
        error = None
        if not reviewer_id:
            error = "reviewer id is required"
        else:
            try:
                resolved_service.confirm_dependency_suggestion(
                    suggestion_id,
                    DependencySuggestionDecisionRequest(by=reviewer_id),
                )
            except (SolomonError, ValueError) as exc:
                error = str(exc)
        return _render_dependencies(
            request,
            resolved_service,
            decision="pending",
            error=error,
            status_code=200 if error is None else 400,
        )

    @app.post("/console/dependencies/suggestions/{suggestion_id}/reject")
    async def reject_dependency(request: Request, suggestion_id: str) -> Response:
        form = await request.form()
        reviewer_id = str(form.get("reviewer_id") or "").strip()
        error = None
        if not reviewer_id:
            error = "reviewer id is required"
        else:
            try:
                resolved_service.reject_dependency_suggestion(
                    suggestion_id,
                    DependencySuggestionDecisionRequest(by=reviewer_id),
                )
            except (SolomonError, ValueError) as exc:
                error = str(exc)
        return _render_dependencies(
            request,
            resolved_service,
            decision="pending",
            error=error,
            status_code=200 if error is None else 400,
        )

    return app


def _render_verification(
    request: Request,
    service: SolomonService,
    *,
    item_id: str | None = None,
    error: str | None = None,
) -> Response:
    rows = _review_rows(service)
    selected_id = item_id or (rows[0]["item"]["id"] if rows else None)
    return TEMPLATES.TemplateResponse(
        request,
        "verification.html",
        {
            "items": rows,
            "selected": _preview_context(request, service, item_id=selected_id, error=error)["selected"],
            "error": error,
        },
    )


def _review_rows(service: SolomonService) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in service.store.get_many():
        currency = service.evaluate_currency(item.id)
        if not _needs_review(item, currency):
            continue
        rows.append(
            {
                "item": item.model_dump(mode="json"),
                "currency": currency,
                "reason": _review_reason(item, currency),
                "source_ref": item.provenance.source_ref,
                "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
            }
        )
    return sorted(rows, key=lambda row: (str(row["item"].get("matter_id") or ""), str(row["item"]["id"])))


def _render_dependencies(
    request: Request,
    service: SolomonService,
    *,
    decision: str,
    item_id: str | None = None,
    authority_id: str | None = None,
    depth: int = 1,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    rows = _suggestion_rows(service, decision=decision, authority_id=authority_id)
    selected_item_id = item_id or (rows[0]["suggestion"]["item_id"] if rows else None)
    return TEMPLATES.TemplateResponse(
        request,
        "dependencies.html",
        {
            "rows": rows,
            "decision": decision,
            "authority_id": authority_id or "",
            "depth": depth,
            "selected": _dependency_graph_context(service, selected_item_id, depth=depth),
            "error": error,
        },
        status_code=status_code,
    )


def _suggestion_rows(
    service: SolomonService,
    *,
    decision: str,
    authority_id: str | None,
) -> list[dict[str, Any]]:
    resolved_decision = _suggestion_decision(decision)
    suggestions = service.dependency_suggestions(decision=resolved_decision, limit=200)
    rows = [_suggestion_row(suggestion) for suggestion in suggestions]
    if authority_id:
        rows = [
            row
            for row in rows
            if authority_id.lower() in str(row["suggestion"]["suggested_edge"]["target_id"]).lower()
            or authority_id.lower() in str(row["suggestion"]["authority_ref"]).lower()
        ]
    return rows


def _suggestion_row(suggestion: DependencySuggestion) -> dict[str, Any]:
    payload = suggestion.model_dump(mode="json")
    return {
        "suggestion": payload,
        "target_id": payload["suggested_edge"]["target_id"],
        "edge_type": payload["suggested_edge"]["edge_type"],
        "confidence": payload["suggested_edge"]["confidence"],
    }


def _dependency_graph_context(
    service: SolomonService,
    item_id: str | None,
    *,
    depth: int,
) -> dict[str, Any] | None:
    if item_id is None:
        return None
    try:
        trace = service.why(item_id)
    except SolomonError:
        return None
    pending = [
        _suggestion_row(suggestion)
        for suggestion in service.dependency_suggestions(item_id=item_id, decision=SuggestionDecision.PENDING, limit=50)
    ]
    return {
        "item": trace.item.model_dump(mode="json"),
        "dependencies": trace.dependencies,
        "dependents": trace.dependents if depth > 1 else [],
        "pending": pending,
        "depth": depth,
    }


def _suggestion_decision(value: str) -> SuggestionDecision | None:
    if value == "all":
        return None
    try:
        return SuggestionDecision(value)
    except ValueError:
        return SuggestionDecision.PENDING


def _needs_review(item: KnowledgeItem, currency: dict[str, Any]) -> bool:
    return (
        str(currency.get("currency_state")) == CurrencyState.STALE_PENDING_REVERIFICATION.value
        or item.verified_state is VerifiedState.NEEDS_REVIEW
        or bool(item.metadata.get("contests"))
        or bool(item.metadata.get("staleness_reasons"))
    )


def _review_reason(item: KnowledgeItem, currency: dict[str, Any]) -> str:
    stale_reasons = currency.get("stale_reasons")
    if isinstance(stale_reasons, list) and stale_reasons:
        first = stale_reasons[0]
        if isinstance(first, dict):
            return str(first.get("reason") or first.get("dependency_id") or "stale dependency")
    contests = item.metadata.get("contests")
    if isinstance(contests, list) and contests:
        first = contests[0]
        if isinstance(first, dict):
            return str(first.get("reason") or "contest")
    explanation = currency.get("explanation")
    if isinstance(explanation, list) and explanation:
        return str(explanation[0])
    return "needs review"


def _preview_context(
    request: Request,
    service: SolomonService,
    *,
    item_id: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    selected = None
    if item_id:
        try:
            trace = service.why(item_id)
            selected = {
                "item": trace.item.model_dump(mode="json"),
                "currency": trace.currency,
                "dependencies": trace.dependencies,
                "dependents": trace.dependents,
                "provenance": trace.provenance,
                "credence_tier": trace.credence_tier,
                "verification": trace.verification,
                "reason": _review_reason(trace.item, trace.currency),
            }
        except SolomonError as exc:
            error = str(exc)
    return {"request": request, "selected": selected, "error": error}


def _validate_decision_form(
    decision: str,
    partner_id: str,
    evidence_ref: str,
    successor_id: str | None,
) -> str | None:
    if decision not in {"reaffirm", "supersede", "retire", "pin"}:
        return "select a decision"
    if not partner_id:
        return "partner id is required"
    if not evidence_ref:
        return "evidence ref is required"
    if decision == "supersede" and successor_id is None:
        return "successor id is required for supersede"
    return None


def _apply_decision(
    service: SolomonService,
    *,
    item_id: str,
    decision: str,
    partner_id: str,
    evidence_ref: str,
    successor_id: str | None,
) -> None:
    if decision == "pin":
        service.pin(
            item_id,
            PinRequest(
                lawyer_id=partner_id,
                reason=evidence_ref,
                actor_tier=CredenceTier.FIRM_AUTHORITATIVE,
            ),
        )
        return
    service.record_verification(
        item_id,
        VerificationRequest(
            by=partner_id,
            outcome=VerificationOutcome(decision),
            successor_id=successor_id,
        ),
    )


def _service_database_url(settings: Settings) -> str:
    if urlparse(settings.database_url).scheme in {"postgres", "postgresql"}:
        return settings.database_url
    if settings.database_url != DEFAULT_DATABASE_URL:
        return settings.database_url
    return str(settings.data_dir / "solomon.sqlite3")


__all__ = ["create_console_app"]
