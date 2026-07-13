# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from solomon.api.auth import AuthPrincipal, AuthRole, mapped_oidc_roles, primary_role, scopes_for_roles
from solomon.api.oidc import OIDCIdentity, OIDCValidationError, OIDCValidator
from solomon.api.service import (
    CandidateClaimDeferralRequest,
    CandidateClaimPromotionRequest,
    CandidateClaimRejectionRequest,
    DependencySuggestionDecisionRequest,
    PinRequest,
    RecallRequest,
    ReviewTaskAssignmentRequest,
    ReviewTaskResolutionRequest,
    ReviewTaskStartRequest,
    SolomonService,
    VerificationAssignmentRequest,
    VerificationRequest,
)
from solomon.audit.journal import AuditAttribution
from solomon.boundary.solomon import SolomonBoundary
from solomon.config import (
    Settings,
    boundary_policy_from_settings,
    credence_policy_from_settings,
    get_settings,
    verification_policy_from_settings,
)
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import CredenceTier, CurrencyState, KnowledgeItem, VerifiedState
from solomon.currency.report import CurrencyMovementReport, ReportScopeKind, render_currency_report_pdf
from solomon.errors import SolomonError
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.telemetry import telemetry_from_settings
from solomon.workflow.models import ReviewTaskPriority, ReviewTaskState

DEFAULT_DATABASE_URL = str(Settings.model_fields["database_url"].default)
PACKAGE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
STATIC_DIR = PACKAGE_DIR / "static"
CONSOLE_READ_ROLES = frozenset({"admin", "curator", "reviewer", "lawyer"})
CONSOLE_CURATE_ROLES = frozenset({"admin", "curator"})
CONSOLE_REVIEW_ROLES = frozenset({"admin", "reviewer", "lawyer"})


def create_console_app(*, settings: Settings | None = None, service: SolomonService | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_service = service or SolomonService(
        data_dir=resolved_settings.data_dir,
        journal_dir=resolved_settings.journal_dir,
        attestation_key=resolved_settings.verification_attestation_key,
        database_url=_service_database_url(resolved_settings),
        verification_policy=verification_policy_from_settings(resolved_settings),
        verification_policy_version=resolved_settings.verification_policy_version,
        credence_policy=credence_policy_from_settings(resolved_settings),
        credence_policy_version=resolved_settings.credence_policy_version,
        telemetry=telemetry_from_settings(
            enabled=resolved_settings.telemetry_enabled,
            service_name=resolved_settings.telemetry_service_name,
            otlp_endpoint=resolved_settings.telemetry_otlp_endpoint,
        ),
        boundary=SolomonBoundary(policy=boundary_policy_from_settings(resolved_settings)),
    )
    app = FastAPI(title="Solomon Console")
    app.state.service = resolved_service
    app.state.console_user_id = resolved_settings.console_user_id
    app.state.oidc_validator = _console_oidc_validator(resolved_settings)
    app.mount("/console/static", StaticFiles(directory=str(STATIC_DIR)), name="console-static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.middleware("http")
    async def console_auth(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not _requires_console_auth(request.url.path):
            return await call_next(request)
        correlation_id = request.headers.get("x-correlation-id") or uuid4().hex
        principal = _console_principal(request, resolved_settings, app.state.oidc_validator)
        if principal is None:
            _record_console_decision(resolved_service, None, correlation_id, request.url.path, "denied")
            return JSONResponse(
                {"detail": "missing or invalid console credentials"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not _console_role_allowed(principal, request.url.path):
            _record_console_decision(resolved_service, principal, correlation_id, request.url.path, "denied")
            return JSONResponse({"detail": "console role is not authorized"}, status_code=403)
        request.state.console_user_id = principal.subject
        request.state.principal = principal
        request.state.correlation_id = correlation_id
        _record_console_decision(resolved_service, principal, correlation_id, request.url.path, "allowed")
        with resolved_service.authorized_as(principal, correlation_id):
            return await call_next(request)

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

    @app.get("/console/claims")
    def claims(request: Request) -> Response:
        return _render_claims(request, resolved_service)

    @app.get("/console/sources")
    def sources(request: Request) -> Response:
        return _render_sources(request, resolved_service)

    @app.get("/console/reviews")
    def reviews(request: Request, state: ReviewTaskState | None = None) -> Response:
        return _render_reviews(request, resolved_service, state=state)

    @app.get("/console/audit-pack")
    def audit_pack(request: Request, item_id: str | None = None, q: str | None = None) -> Response:
        return _render_audit_pack(request, resolved_service, item_id=item_id, query=q)

    @app.get("/console/currency-report")
    def currency_report(
        request: Request,
        period_start: str | None = None,
        period_end: str | None = None,
        scope: str = "firm",
        practice_area: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> Response:
        return _render_currency_report(
            request,
            resolved_service,
            period_start=period_start,
            period_end=period_end,
            scope=scope,
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )

    @app.get("/console/currency-report/export")
    def export_currency_report(
        period_start: str,
        period_end: str,
        scope: str = "firm",
        practice_area: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        format: str = "json",
    ) -> Response:
        try:
            report = _currency_report_from_params(
                resolved_service,
                period_start=period_start,
                period_end=period_end,
                scope=scope,
                practice_area=practice_area,
                matter_id=matter_id,
                client_id=client_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if format == "pdf":
            return Response(
                content=render_currency_report_pdf(report),
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="currency-report.pdf"'},
            )
        manifest, journal_jsonl = _exported_currency_report_pack(resolved_service, report)
        return JSONResponse(
            content={
                "schema": "solomon.console.currency_report_pack.v1",
                "report": report.model_dump(mode="json"),
                "manifest": manifest,
                "journal_jsonl": journal_jsonl,
            },
            headers={"Content-Disposition": 'attachment; filename="currency-report-pack.json"'},
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

    @app.post("/console/verification/items/{item_id}/assign")
    async def assign_verification(request: Request, item_id: str) -> Response:
        form = await request.form()
        reviewer_id = str(form.get("reviewer_id") or "").strip()
        assigned_by = str(form.get("assigned_by") or request.state.console_user_id).strip()
        role = str(form.get("role") or "").strip() or None
        basis = str(form.get("basis") or "").strip() or None
        error = None
        if not reviewer_id:
            error = "reviewer id is required"
        else:
            try:
                resolved_service.assign_verification(
                    item_id,
                    VerificationAssignmentRequest(
                        assigned_by=assigned_by,
                        reviewer_id=reviewer_id,
                        role=role,
                        basis=basis,
                    ),
                )
            except (SolomonError, ValueError) as exc:
                error = str(exc)
        return TEMPLATES.TemplateResponse(
            request,
            "partials/verification_preview.html",
            _preview_context(request, resolved_service, item_id=item_id, error=error),
            status_code=200 if error is None else 400,
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

    @app.post("/console/claims/{candidate_id}/{action}")
    async def claim_action(request: Request, candidate_id: str, action: str) -> Response:
        form = await request.form()
        by = str(form.get("by") or request.state.console_user_id).strip()
        reason = str(form.get("reason") or "").strip()
        error = None
        if not by:
            error = "curator id is required"
        elif action in {"reject", "defer"} and not reason:
            error = "reason is required"
        else:
            try:
                if action == "promote":
                    resolved_service.promote_candidate_claim(candidate_id, CandidateClaimPromotionRequest(by=by))
                elif action == "reject":
                    resolved_service.reject_candidate_claim(
                        candidate_id,
                        CandidateClaimRejectionRequest(by=by, reason=reason),
                    )
                elif action == "defer":
                    resolved_service.defer_candidate_claim(
                        candidate_id,
                        CandidateClaimDeferralRequest(by=by, reason=reason),
                    )
                else:
                    error = "unsupported candidate action"
            except (SolomonError, ValueError) as exc:
                error = str(exc)
        return _render_claims(request, resolved_service, error=error, status_code=200 if error is None else 400)

    @app.post("/console/sources/{source_id}/sync")
    def sync_source(request: Request, source_id: str) -> Response:
        error = None
        try:
            resolved_service.sync_document_source(source_id)
        except (SolomonError, ValueError) as exc:
            error = str(exc)
        return _render_sources(request, resolved_service, error=error, status_code=200 if error is None else 400)

    @app.post("/console/sources/{source_id}/documents/{document_id}/retry-extraction")
    def retry_source_extraction(request: Request, source_id: str, document_id: str) -> Response:
        error = None
        try:
            resolved_service.retry_source_document_extraction(source_id, document_id)
        except (SolomonError, ValueError) as exc:
            error = str(exc)
        return _render_sources(request, resolved_service, error=error, status_code=200 if error is None else 400)

    @app.post("/console/reviews/{task_id}/{action}")
    async def review_action(request: Request, task_id: str, action: str) -> Response:
        form = await request.form()
        reviewer_id = str(form.get("reviewer_id") or "").strip()
        error = None
        try:
            if action == "assign":
                resolved_service.assign_review_task(
                    task_id,
                    ReviewTaskAssignmentRequest(
                        reviewer_id=reviewer_id,
                        assigned_by=str(form.get("assigned_by") or request.state.console_user_id),
                    ),
                )
            elif action == "start":
                resolved_service.start_review_task(task_id, ReviewTaskStartRequest(reviewer_id=reviewer_id))
            elif action == "resolve":
                resolved_service.resolve_review_task(
                    task_id,
                    ReviewTaskResolutionRequest(
                        reviewer_id=reviewer_id,
                        verification=VerificationRequest(
                            by=reviewer_id,
                            outcome=VerificationOutcome(str(form.get("outcome") or "reaffirm")),
                            basis=str(form.get("basis") or "").strip() or None,
                            source_ref=str(form.get("source_ref") or "").strip() or None,
                        ),
                    ),
                )
            else:
                error = "unsupported review action"
        except (SolomonError, ValueError) as exc:
            error = str(exc)
        return _render_reviews(request, resolved_service, error=error, status_code=200 if error is None else 400)

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

    @app.get("/console/audit-pack/items/{item_id}/export")
    def export_audit_pack(item_id: str, format: str = "json") -> Response:
        try:
            trace = resolved_service.why(item_id)
        except SolomonError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if format == "pdf":
            return Response(
                content=_minimal_pdf(
                    [
                        "Solomon audit pack",
                        f"item_id: {trace.item.id}",
                        f"currency_state: {trace.currency['currency_state']}",
                        f"source_ref: {trace.provenance['source_ref']}",
                        f"dependencies: {len(trace.dependencies)}",
                        f"contradictions: {len(trace.contradictions)}",
                        f"verification_events: {len(trace.verification.get('history', []))}",
                    ]
                ),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{item_id}-audit-pack.pdf"'},
            )
        manifest, journal_jsonl = _exported_pack_files(resolved_service)
        return JSONResponse(
            content=_audit_pack_payload(trace, manifest=manifest, journal_jsonl=journal_jsonl),
            headers={"Content-Disposition": f'attachment; filename="{item_id}-audit-pack.json"'},
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
            "active_page": "verification",
        },
    )


def _render_claims(
    request: Request,
    service: SolomonService,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    return TEMPLATES.TemplateResponse(
        request,
        "claims.html",
        {"rows": _claim_rows(service), "error": error, "active_page": "claims"},
        status_code=status_code,
    )


def _render_sources(
    request: Request,
    service: SolomonService,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    return TEMPLATES.TemplateResponse(
        request,
        "sources.html",
        {"rows": _source_rows(service), "error": error, "active_page": "sources"},
        status_code=status_code,
    )


def _source_rows(service: SolomonService) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in service.document_store.list_sources():
        latest_documents = service.document_store.list_latest_documents(source.id)
        checkpoint = service.document_store.get_sync_checkpoint(source.id)
        rows.append(
            {
                "source": source.model_dump(mode="json"),
                "health": service.document_source_health(source.id).model_dump(mode="json"),
                "checkpoint": checkpoint.model_dump(mode="json") if checkpoint is not None else None,
                "runs": [run.model_dump(mode="json") for run in service.document_source_sync_runs(source.id)],
                "failures": [
                    document.model_dump(mode="json")
                    for document in latest_documents
                    if document.extraction_state.value == "rejected"
                ],
                "can_sync": source.kind.value == "filesystem",
            }
        )
    return sorted(rows, key=lambda row: (str(row["source"]["name"]), str(row["source"]["id"])))


def _render_reviews(
    request: Request,
    service: SolomonService,
    *,
    state: ReviewTaskState | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> Response:
    return TEMPLATES.TemplateResponse(
        request,
        "reviews.html",
        {"rows": _review_task_rows(service, state=state), "error": error, "active_page": "reviews"},
        status_code=status_code,
    )


def _review_task_rows(service: SolomonService, *, state: ReviewTaskState | None) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for task in service.review_tasks(state=state):
        event = service.workflow_store.get_authority_event(task.event_id)
        trace = service.why(task.item_id)
        due_at = task.created_at + _review_sla(task.priority)
        rows.append(
            {
                "task": task.model_dump(mode="json"),
                "event": event.model_dump(mode="json"),
                "item": trace.item.model_dump(mode="json"),
                "due_at": due_at.isoformat(),
                "overdue": task.state is not ReviewTaskState.RESOLVED and due_at < now,
            }
        )
    return sorted(rows, key=lambda row: (not row["overdue"], row["due_at"], row["task"]["id"]))


def _review_sla(priority: ReviewTaskPriority) -> timedelta:
    return {
        ReviewTaskPriority.URGENT: timedelta(days=1),
        ReviewTaskPriority.HIGH: timedelta(days=3),
        ReviewTaskPriority.NORMAL: timedelta(days=7),
    }[priority]


def _claim_rows(service: SolomonService) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in service.document_store.list_sources():
        for document in service.document_store.list_documents(source.id):
            for candidate in service.document_store.list_candidates(document.id):
                entries = [
                    entry.model_dump(mode="json")
                    for entry in service.audit.list_entries()
                    if entry.payload.get("candidate_id") == candidate.id
                ]
                rows.append(
                    {
                        "candidate": candidate.model_dump(mode="json"),
                        "document": document.model_dump(mode="json"),
                        "source": source.model_dump(mode="json"),
                        "audit": entries,
                    }
                )
    return sorted(
        rows,
        key=lambda row: (
            row["candidate"]["status"] != "pending",
            str(row["candidate"]["created_at"]),
            str(row["candidate"]["id"]),
        ),
    )


def _requires_console_auth(path: str) -> bool:
    return (path == "/console" or path.startswith("/console/")) and not path.startswith("/console/static/")


def _console_oidc_validator(settings: Settings) -> OIDCValidator | None:
    if settings.oidc_issuer is None or settings.oidc_audience is None:
        return None
    return OIDCValidator(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        clock_skew_seconds=settings.oidc_clock_skew_seconds,
        cache_seconds=settings.oidc_jwks_cache_seconds,
    )


def _console_principal(
    request: Request,
    settings: Settings,
    validator: OIDCValidator | None,
) -> AuthPrincipal | None:
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        if validator is not None or settings.console_bearer_token is not None or settings.sku != "local":
            return None
        role: AuthRole = "admin"
        roles = frozenset({role})
        return AuthPrincipal(
            subject=settings.console_user_id,
            role=role,
            tenant_id=None,
            scopes=scopes_for_roles(roles),
            roles=roles,
        )
    if validator is None:
        if settings.console_bearer_token is None or not compare_digest(supplied, settings.console_bearer_token):
            return None
        role = cast(AuthRole, settings.console_role)
        roles = frozenset({role})
        return AuthPrincipal(
            subject=settings.console_user_id,
            role=role,
            tenant_id=None,
            scopes=scopes_for_roles(roles),
            roles=roles,
        )
    try:
        identity = validator.validate(supplied)
    except OIDCValidationError:
        return None
    return _oidc_console_principal(identity, settings)


def _oidc_console_principal(identity: OIDCIdentity, settings: Settings) -> AuthPrincipal | None:
    roles = mapped_oidc_roles(
        identity.claims,
        claim_name=settings.oidc_role_claim,
        mappings=settings.oidc_role_mappings,
    )
    if not roles:
        return None
    return AuthPrincipal(
        subject=identity.subject,
        role=primary_role(roles),
        tenant_id=None,
        scopes=scopes_for_roles(roles),
        roles=roles,
    )


def _console_role_allowed(principal: AuthPrincipal, path: str) -> bool:
    roles = principal.roles or frozenset({principal.role})
    if path.startswith(("/console/sources", "/console/claims", "/console/dependencies")):
        return bool(roles & CONSOLE_CURATE_ROLES)
    if path.startswith(("/console/verification", "/console/reviews")):
        return bool(roles & CONSOLE_REVIEW_ROLES)
    return bool(roles & CONSOLE_READ_ROLES)


def _record_console_decision(
    service: SolomonService,
    principal: AuthPrincipal | None,
    correlation_id: str,
    path: str,
    decision: str,
) -> None:
    roles = principal.roles if principal is not None else frozenset()
    service.audit.append(
        "console_authorization",
        {"path": path, "decision": decision, "roles": sorted(roles)},
        attribution=AuditAttribution(
            actor_id=principal.subject if principal is not None else None,
            correlation_id=correlation_id,
        ),
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
                "reviewer_id": item.metadata.get("verification_reviewer_id"),
                "verification_status": item.metadata.get("verification_status"),
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
            "active_page": "dependencies",
        },
        status_code=status_code,
    )


def _render_audit_pack(
    request: Request,
    service: SolomonService,
    *,
    item_id: str | None,
    query: str | None,
    error: str | None = None,
) -> Response:
    candidates = _audit_candidates(service, query)
    selected_id = item_id or (candidates[0]["id"] if candidates else None)
    selected = _audit_context(service, selected_id)
    return TEMPLATES.TemplateResponse(
        request,
        "audit_pack.html",
        {"candidates": candidates, "selected": selected, "q": query or "", "error": error, "active_page": "audit_pack"},
    )


def _render_currency_report(
    request: Request,
    service: SolomonService,
    *,
    period_start: str | None,
    period_end: str | None,
    scope: str,
    practice_area: str | None,
    matter_id: str | None,
    client_id: str | None,
) -> Response:
    start, end = _default_report_period(period_start, period_end)
    error = None
    report = None
    try:
        report = _currency_report_from_params(
            service,
            period_start=start,
            period_end=end,
            scope=scope,
            practice_area=practice_area,
            matter_id=matter_id,
            client_id=client_id,
        )
    except ValueError as exc:
        error = str(exc)
    return TEMPLATES.TemplateResponse(
        request,
        "currency_report.html",
        {
            "report": report.model_dump(mode="json") if report else None,
            "period_start": start,
            "period_end": end,
            "scope": scope,
            "practice_area": practice_area or "",
            "matter_id": matter_id or "",
            "client_id": client_id or "",
            "error": error,
            "active_page": "currency_report",
        },
        status_code=200 if error is None else 400,
    )


def _currency_report_from_params(
    service: SolomonService,
    *,
    period_start: str,
    period_end: str,
    scope: str,
    practice_area: str | None,
    matter_id: str | None,
    client_id: str | None,
) -> CurrencyMovementReport:
    if scope not in {"firm", "practice_area", "matter"}:
        raise ValueError("unsupported currency report scope")
    return service.currency_report(
        period_start=datetime.fromisoformat(period_start.replace("Z", "+00:00")),
        period_end=datetime.fromisoformat(period_end.replace("Z", "+00:00")),
        scope=cast(ReportScopeKind, scope),
        practice_area=practice_area or None,
        matter_id=matter_id or None,
        client_id=client_id or None,
    )


def _default_report_period(period_start: str | None, period_end: str | None) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = period_start or datetime(now.year, 1, 1, tzinfo=timezone.utc).isoformat()
    end = period_end or now.isoformat()
    return start, end


def _audit_candidates(service: SolomonService, query: str | None) -> list[dict[str, Any]]:
    if query:
        try:
            item = service.why(query).item
            return [item.model_dump(mode="json")]
        except SolomonError:
            results = service.recall(RecallRequest(query=query, review_mode=True, limit=10))
            return [result["item"] for result in results]
    return [item.model_dump(mode="json") for item in service.store.get_many()[:20]]


def _audit_context(service: SolomonService, item_id: str | None) -> dict[str, Any] | None:
    if item_id is None:
        return None
    try:
        trace = service.why(item_id)
    except SolomonError:
        return None
    verification = service.audit.verify().model_dump(mode="json")
    manifest, _journal_jsonl = _exported_pack_files(service)
    return {
        "item": trace.item.model_dump(mode="json"),
        "currency": trace.currency,
        "dependencies": trace.dependencies,
        "dependents": trace.dependents,
        "contradictions": trace.contradictions,
        "provenance": trace.provenance,
        "credence_tier": trace.credence_tier,
        "verification": trace.verification,
        "journal": verification,
        "manifest": manifest,
    }


def _audit_pack_payload(trace: Any, *, manifest: dict[str, Any], journal_jsonl: str) -> dict[str, Any]:
    return {
        "schema": "solomon.console.audit_pack.v1",
        "knowledge_item_id": trace.item.id,
        "item": trace.item.model_dump(mode="json"),
        "currency": trace.currency,
        "dependencies": trace.dependencies,
        "dependents": trace.dependents,
        "contradictions": trace.contradictions,
        "provenance": trace.provenance,
        "credence_tier": trace.credence_tier,
        "verification": trace.verification,
        "verification_history": trace.verification.get("history", []),
        "manifest": manifest,
        "journal_jsonl": journal_jsonl,
    }


def _exported_pack_files(service: SolomonService) -> tuple[dict[str, Any], str]:
    with TemporaryDirectory(prefix="solomon-console-audit-") as temp_dir:
        pack_dir = service.export_audit_pack(Path(temp_dir))
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        journal_jsonl = (pack_dir / str(manifest["journal_file"])).read_text(encoding="utf-8")
    return manifest, journal_jsonl


def _exported_currency_report_pack(
    service: SolomonService,
    report: CurrencyMovementReport,
) -> tuple[dict[str, Any], str]:
    with TemporaryDirectory(prefix="solomon-console-currency-report-") as temp_dir:
        pack_dir = service.export_currency_report_pack(Path(temp_dir), report)
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        journal_jsonl = (pack_dir / str(manifest["journal_file"])).read_text(encoding="utf-8")
    return manifest, journal_jsonl


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
                "verification_history": trace.verification.get("history", []),
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
            basis=evidence_ref,
            source_ref=evidence_ref,
            successor_id=successor_id,
        ),
    )


def _service_database_url(settings: Settings) -> str:
    if urlparse(settings.database_url).scheme in {"postgres", "postgresql"}:
        return settings.database_url
    if settings.database_url != DEFAULT_DATABASE_URL:
        return settings.database_url
    return str(settings.data_dir / "solomon.sqlite3")


def _minimal_pdf(lines: list[str]) -> bytes:
    text_commands = ["BT", "/F1 12 Tf", "72 740 Td"]
    for index, line in enumerate(lines):
        if index:
            text_commands.append("0 -18 Td")
        text_commands.append(f"({_pdf_escape(line)}) Tj")
    text_commands.append("ET")
    stream = "\n".join(text_commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    chunks = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    chunks.extend(
        [
            *xref,
            b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(chunks)


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


__all__ = ["create_console_app"]
