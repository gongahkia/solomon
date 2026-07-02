#!/usr/bin/env python3
"""Generate the deterministic ContinuityBench v0 dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks" / "continuity" / "dataset" / "continuitybench-v0.json"
DEFAULT_HASH_OUTPUT = DEFAULT_OUTPUT.with_suffix(".sha256")
SEED = 0xC0A71_20260702
BASE_TIME = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--hash-output", type=Path, default=DEFAULT_HASH_OUTPUT)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    dataset = build_dataset(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    digest = dataset_hash(dataset)
    args.hash_output.write_text(f"sha256:{digest}  {args.output.name}\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"wrote {args.hash_output}")
    print(f"sha256:{digest}")
    return 0


def build_dataset(seed: int) -> dict[str, Any]:
    tasks = [
        *supersession_tasks(),
        *contradiction_tasks(),
        *evidence_quality_tasks(),
        *stable_recall_tasks(),
    ]
    random.Random(seed).shuffle(tasks)
    for index, task in enumerate(tasks, start=1):
        task["order"] = index

    categories = Counter(str(task["category"]) for task in tasks)
    domains = Counter(str(task["domain"]) for task in tasks)
    return {
        "schema_version": "continuitybench.v0",
        "metadata": {
            "name": "ContinuityBench v0",
            "task_count": len(tasks),
            "seed": seed,
            "authorship": "synthetic templated tasks generated in-repo; no private data; no LLM-generated facts",
            "review_status": "templates and generated dataset are intended for human review in code review",
            "category_counts": dict(sorted(categories.items())),
            "domain_counts": dict(sorted(domains.items())),
            "primary_audience": "coding agents and agent-framework builders",
        },
        "tasks": tasks,
    }


def dataset_hash(dataset: dict[str, Any]) -> str:
    canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def supersession_tasks() -> list[dict[str, Any]]:
    return [
        *[
            supersession_task(
                f"rename-signature-{index:04d}",
                "coding",
                slug,
                old,
                new,
                query,
                current,
                stale,
                f"src/{slug}.py",
                index,
            )
            for index, (slug, old, new, query, current, stale) in enumerate(
                coding_supersession_specs(), start=1
            )
        ],
        *[
            supersession_task(
                f"general-change-{index:04d}",
                "general",
                slug,
                old,
                new,
                query,
                current,
                stale,
                f"profile/{slug}",
                index + 64,
            )
            for index, (slug, old, new, query, current, stale) in enumerate(
                general_supersession_specs(), start=1
            )
        ],
    ]


def supersession_task(
    task_id: str,
    domain: str,
    slug: str,
    old: str,
    new: str,
    query: str,
    current: str,
    stale: str,
    ref: str,
    offset: int,
) -> dict[str, Any]:
    old_fact = f"{slug}:v1"
    current_fact = f"{slug}:v2"
    return {
        "task_id": task_id,
        "category": "supersession",
        "domain": domain,
        "events": [
            event(f"{task_id}:old", offset, old, "file", ref, 1, establishes=old_fact),
            event(
                f"{task_id}:current",
                offset + 1,
                new,
                "file",
                ref,
                2,
                establishes=current_fact,
                supersedes=old_fact,
            ),
        ],
        "query": {
            "t": iso(offset + 7),
            "text": query,
            "target_fact": current_fact,
        },
        "answers": {"current": current, "stale": stale},
    }


def contradiction_tasks() -> list[dict[str, Any]]:
    specs = [
        *coding_contradiction_specs(),
        *general_contradiction_specs(),
    ]
    return [
        contradiction_task(
            f"contradiction-{index:04d}",
            domain,
            slug,
            weak,
            strong,
            query,
            authoritative,
            rejected,
            reason,
            index + 100,
        )
        for index, (domain, slug, weak, strong, query, authoritative, rejected, reason) in enumerate(
            specs, start=1
        )
    ]


def contradiction_task(
    task_id: str,
    domain: str,
    slug: str,
    weak: str,
    strong: str,
    query: str,
    authoritative: str,
    rejected: str,
    reason: str,
    offset: int,
) -> dict[str, Any]:
    weak_fact = f"{slug}:weak"
    strong_fact = f"{slug}:authoritative"
    return {
        "task_id": task_id,
        "category": "contradiction",
        "domain": domain,
        "events": [
            event(f"{task_id}:weak", offset, weak, "todo", f"{slug}:note", 1, establishes=weak_fact),
            event(
                f"{task_id}:authoritative",
                offset,
                strong,
                "file",
                f"{slug}:source",
                3,
                establishes=strong_fact,
            ),
        ],
        "query": {
            "t": iso(offset + 5),
            "text": query,
            "target_fact": strong_fact,
        },
        "answers": {"authoritative": authoritative, "rejected": rejected},
        "resolution": {
            "authoritative_event_id": f"{task_id}:authoritative",
            "authoritative_fact": strong_fact,
            "reason": reason,
        },
    }


def evidence_quality_tasks() -> list[dict[str, Any]]:
    specs = [*coding_evidence_specs(), *general_evidence_specs()]
    return [
        evidence_quality_task(
            f"evidence-quality-{index:04d}",
            domain,
            slug,
            content,
            query,
            answer,
            ((index - 1) % 4) + 1,
            index + 200,
        )
        for index, (domain, slug, content, query, answer) in enumerate(specs, start=1)
    ]


def evidence_quality_task(
    task_id: str,
    domain: str,
    slug: str,
    content: str,
    query: str,
    answer: str,
    strength: int,
    offset: int,
) -> dict[str, Any]:
    kind, corroboration = {
        1: ("chat", 1),
        2: ("runtime-log", 2),
        3: ("file", 3),
        4: ("human", 4),
    }[strength]
    fact = f"{slug}:evidence"
    return {
        "task_id": task_id,
        "category": "evidence-quality",
        "domain": domain,
        "events": [
            event(
                f"{task_id}:evidence",
                offset,
                content,
                kind,
                f"{kind}/{slug}",
                corroboration,
                establishes=fact,
                evidence_strength=strength,
            )
        ],
        "query": {"t": iso(offset + 3), "text": query, "target_fact": fact},
        "answers": {"current": answer},
        "evidence": {
            "fact": fact,
            "strength": strength,
            "scale": "1=single uncorroborated, 4=human affirmed",
        },
    }


def stable_recall_tasks() -> list[dict[str, Any]]:
    specs = [*coding_stable_specs(), *general_stable_specs()]
    return [
        stable_recall_task(
            f"stable-recall-{index:04d}",
            domain,
            slug,
            content,
            query,
            answer,
            index + 300,
        )
        for index, (domain, slug, content, query, answer) in enumerate(specs, start=1)
    ]


def stable_recall_task(
    task_id: str,
    domain: str,
    slug: str,
    content: str,
    query: str,
    answer: str,
    offset: int,
) -> dict[str, Any]:
    fact = f"{slug}:stable"
    return {
        "task_id": task_id,
        "category": "stable-recall",
        "domain": domain,
        "events": [
            event(f"{task_id}:stable", offset, content, "file", f"stable/{slug}", 2, establishes=fact)
        ],
        "query": {"t": iso(offset + 4), "text": query, "target_fact": fact},
        "answers": {"current": answer},
    }


def event(
    event_id: str,
    day_offset: int,
    content: str,
    provenance_kind: str,
    provenance_ref: str,
    corroboration: int,
    *,
    establishes: str,
    supersedes: str | None = None,
    evidence_strength: int | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "kind": provenance_kind,
        "ref": provenance_ref,
        "corroboration": corroboration,
    }
    if evidence_strength is not None:
        provenance["evidence_strength"] = evidence_strength
    return {
        "event_id": event_id,
        "t": iso(day_offset),
        "content": content,
        "provenance": provenance,
        "establishes": establishes,
        "supersedes": supersedes,
    }


def iso(day_offset: int) -> str:
    return (BASE_TIME + timedelta(days=day_offset)).isoformat().replace("+00:00", "Z")


def coding_supersession_specs() -> list[tuple[str, str, str, str, str, str]]:
    function_specs = [
        ("user-fetch", "fetch_user(id: int) -> User", "async get_user(id: int) -> Optional[User]"),
        ("invoice-load", "load_invoice(id: str) -> Invoice", "async get_invoice(id: str) -> InvoiceDTO"),
        ("token-issue", "issue_token(user_id: str) -> str", "mint_session_token(user_id: str, ttl_s: int) -> Token"),
        ("report-build", "build_report(range: DateRange) -> Report", "compile_report(range: DateRange, format: str) -> bytes"),
        ("profile-save", "save_profile(profile: Profile) -> bool", "upsert_profile(profile: Profile) -> Profile"),
        ("search-run", "search(q: str) -> list[Result]", "async search_index(query: str, limit: int) -> list[Result]"),
        ("cache-read", "read_cache(key: str) -> bytes", "read_cache(key: str) -> bytes | None"),
        ("audit-write", "write_audit(event: dict) -> None", "append_audit_event(event: AuditEvent) -> EventId"),
        ("job-enqueue", "enqueue_job(name: str) -> str", "enqueue_job(name: str, priority: int) -> JobId"),
        ("file-open", "open_file(path: str) -> File", "open_workspace_file(path: Path) -> WorkspaceFile"),
        ("flag-check", "is_enabled(flag: str) -> bool", "flag_enabled(flag: str, actor_id: str) -> bool"),
        ("payment-capture", "capture(amount: int) -> Receipt", "capture_payment(amount_cents: int, idempotency_key: str) -> Receipt"),
        ("image-resize", "resize(image: bytes) -> bytes", "resize_image(image: bytes, max_px: int) -> bytes"),
        ("email-send", "send_email(to: str, body: str) -> bool", "send_email(message: EmailMessage) -> MessageId"),
        ("metric-record", "record_metric(name: str, value: float) -> None", "record_metric(name: str, value: float, tags: dict[str, str]) -> None"),
        ("session-close", "close_session(id: str) -> None", "revoke_session(session_id: str, reason: str) -> None"),
    ]
    function_tasks = [
        (
            slug,
            f"Function `{old}` is the current API.",
            f"Function changed: `{old}` was replaced by `{new}`.",
            f"What is the current signature for {slug.replace('-', ' ')}?",
            new,
            old,
        )
        for slug, old, new in function_specs
    ]

    route_specs = [
        ("users-route", "/api/v1/users/{id}", "/api/v2/users/{id}"),
        ("invoices-route", "/api/v1/invoices/{id}", "/api/v3/billing/invoices/{id}"),
        ("search-route", "/api/search", "/api/v2/search"),
        ("uploads-route", "/upload", "/api/v2/uploads"),
        ("health-route", "/status", "/healthz"),
        ("metrics-route", "/metrics", "/internal/metrics"),
        ("teams-route", "/api/teams/{id}", "/api/orgs/{org_id}/teams/{id}"),
        ("alerts-route", "/api/alerts", "/api/v2/incidents"),
        ("exports-route", "/api/export", "/api/v2/exports"),
        ("sessions-route", "/api/sessions/{id}", "/api/v2/auth/sessions/{id}"),
        ("comments-route", "/api/comments", "/api/v2/threads/comments"),
        ("files-route", "/api/files/{id}", "/api/v2/workspaces/files/{id}"),
    ]
    route_tasks = [
        (
            slug,
            f"The {slug.replace('-', ' ')} endpoint is `{old}`.",
            f"The {slug.replace('-', ' ')} endpoint moved to `{new}`.",
            f"What endpoint should callers use for {slug.replace('-', ' ')}?",
            new,
            old,
        )
        for slug, old, new in route_specs
    ]

    config_specs = [
        ("checkout-flag", "checkout_disable_all", "checkout_halt_writes"),
        ("search-index", "SEARCH_INDEX_V1", "SEARCH_INDEX_ACTIVE"),
        ("billing-mode", "BILLING_LEGACY_MODE", "BILLING_LEDGER_MODE"),
        ("cache-ttl", "PROFILE_CACHE_TTL_MINUTES", "PROFILE_CACHE_TTL_SECONDS"),
        ("queue-name", "jobs_default", "jobs_interactive"),
        ("trace-sampler", "TRACE_SAMPLE_RATE", "OTEL_TRACES_SAMPLER_ARG"),
        ("avatar-bucket", "avatars-v1", "user-media-prod"),
        ("feature-rollout", "rollout_percent", "traffic_allocation_basis_points"),
        ("retry-budget", "MAX_RETRIES", "RETRY_BUDGET_MS"),
        ("rate-limit", "RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_PER_SECOND"),
        ("tenant-mode", "SINGLE_TENANT", "TENANCY_MODE"),
        ("admin-role", "admin_user", "workspace_admin"),
    ]
    config_tasks = [
        (
            slug,
            f"The active config key for {slug.replace('-', ' ')} is `{old}`.",
            f"The active config key for {slug.replace('-', ' ')} was renamed to `{new}`.",
            f"What config key is current for {slug.replace('-', ' ')}?",
            new,
            old,
        )
        for slug, old, new in config_specs
    ]

    dependency_specs = [
        ("redis-client", "redis-py 4.6", "redis-py 5.1"),
        ("http-client", "reqwest 0.11", "reqwest 0.12"),
        ("react-router", "react-router 6.22", "react-router 7.0"),
        ("pydantic", "pydantic 1.10", "pydantic 2.8"),
        ("axum", "axum 0.7", "axum 0.8"),
        ("tokio", "tokio 1.38", "tokio 1.44"),
        ("sqlalchemy", "SQLAlchemy 1.4", "SQLAlchemy 2.0"),
        ("vite", "vite 5", "vite 6"),
        ("swift-tools", "Swift tools 5.10", "Swift tools 6.0"),
        ("pytest", "pytest 7", "pytest 8"),
        ("node-runtime", "Node 20", "Node 22"),
        ("postgres", "PostgreSQL 15", "PostgreSQL 16"),
    ]
    dependency_tasks = [
        (
            slug,
            f"The project depends on {old}.",
            f"The project dependency was bumped from {old} to {new}.",
            f"What dependency version is current for {slug.replace('-', ' ')}?",
            new,
            old,
        )
        for slug, old, new in dependency_specs
    ]

    decision_specs = [
        ("auth-state", "store auth state in localStorage", "store auth state in httpOnly cookies"),
        ("billing-ledger", "mutate invoice totals in place", "append ledger adjustments"),
        ("search-indexing", "index documents synchronously on write", "enqueue indexing after commit"),
        ("migration-style", "edit production rows manually", "ship versioned idempotent migrations"),
        ("cache-policy", "cache profile reads for 30 minutes", "cache profile reads for 5 minutes"),
        ("error-format", "return plain text errors", "return RFC 7807 problem details"),
        ("image-storage", "store images in Postgres bytea", "store images in object storage"),
        ("tenant-routing", "route tenants by subdomain", "route tenants by signed workspace id"),
        ("audit-retention", "truncate audit logs after 30 days", "retain append-only audit logs"),
        ("worker-scaling", "scale workers manually", "scale workers from queue depth"),
        ("schema-validation", "validate only at API boundary", "validate at API and job boundaries"),
        ("release-flow", "deploy direct from main", "deploy from signed release tags"),
    ]
    decision_tasks = [
        (
            slug,
            f"Design decision: {old}.",
            f"Design decision reversed: {new}.",
            f"What is the current design decision for {slug.replace('-', ' ')}?",
            new,
            old,
        )
        for slug, old, new in decision_specs
    ]

    return function_tasks + route_tasks + config_tasks + dependency_tasks + decision_tasks


def general_supersession_specs() -> list[tuple[str, str, str, str, str, str]]:
    specs = [
        ("office-city", "Avery works from Austin.", "Avery works from Seattle.", "Where does Avery work now?", "Seattle", "Austin"),
        ("coffee-order", "Mina prefers oat latte.", "Mina switched to black coffee.", "What coffee does Mina prefer now?", "black coffee", "oat latte"),
        ("gym-day", "Jordan goes to the gym on Mondays.", "Jordan moved gym day to Thursdays.", "What is Jordan's current gym day?", "Thursdays", "Mondays"),
        ("phone-number", "Rae's support phone ends in 0142.", "Rae's support phone ends in 7720.", "What are Rae's current support phone ending digits?", "7720", "0142"),
        ("diet-note", "Sam eats shellfish.", "Sam now avoids shellfish.", "What is Sam's current shellfish preference?", "avoids shellfish", "eats shellfish"),
        ("timezone", "Noor schedules in UTC.", "Noor schedules in Europe/Berlin.", "What timezone does Noor use now?", "Europe/Berlin", "UTC"),
        ("delivery-address", "Kai's packages go to Dock A.", "Kai's packages go to Dock C.", "Where should Kai's packages go now?", "Dock C", "Dock A"),
        ("language-choice", "Lee prefers emails in English.", "Lee prefers emails in Spanish.", "What language should Lee's emails use now?", "Spanish", "English"),
        ("meeting-room", "The weekly sync uses Room Cedar.", "The weekly sync uses Room Maple.", "Which room is current for the weekly sync?", "Room Maple", "Room Cedar"),
        ("travel-hub", "Priya flies out of SFO.", "Priya flies out of OAK.", "Which airport does Priya use now?", "OAK", "SFO"),
        ("subscription-plan", "Morgan is on the Basic plan.", "Morgan is on the Pro plan.", "What plan is Morgan on now?", "Pro", "Basic"),
        ("newsletter-topic", "The newsletter focuses on security.", "The newsletter focuses on data engineering.", "What topic is current for the newsletter?", "data engineering", "security"),
        ("billing-contact", "The billing contact is Theo.", "The billing contact is Imani.", "Who is the current billing contact?", "Imani", "Theo"),
        ("backup-day", "Backups run on Friday.", "Backups run on Tuesday.", "Which backup day is current?", "Tuesday", "Friday"),
        ("printer-location", "The color printer is near reception.", "The color printer moved to floor 3.", "Where is the color printer now?", "floor 3", "near reception"),
        ("parking-gate", "Use parking gate north.", "Use parking gate west.", "Which parking gate is current?", "west", "north"),
    ]
    return specs


def coding_contradiction_specs() -> list[tuple[str, str, str, str, str, str, str, str]]:
    specs = []
    for index in range(1, 21):
        slug = f"parser-null-{index:02d}"
        specs.append(
            (
                "coding",
                slug,
                f"TODO note says parser_{index} accepts null records.",
                f"Source and tests show parser_{index} rejects null records with ValueError.",
                f"Does parser_{index} accept null records?",
                "rejects null records with ValueError",
                "accepts null records",
                "source_and_tests_have_higher_corroboration_than_todo",
            )
        )
    for index in range(1, 11):
        slug = f"cache-mode-{index:02d}"
        specs.append(
            (
                "coding",
                slug,
                f"Old docs say cache layer {index} is write-through.",
                f"Current implementation records cache layer {index} as write-around.",
                f"What cache mode does layer {index} use?",
                "write-around",
                "write-through",
                "implementation_beats_old_docs",
            )
        )
    for index in range(1, 11):
        slug = f"deploy-target-{index:02d}"
        specs.append(
            (
                "coding",
                slug,
                f"Runbook draft says service {index} deploys to staging-a.",
                f"Signed release manifest says service {index} deploys to staging-b.",
                f"Where does service {index} deploy?",
                "staging-b",
                "staging-a",
                "signed_manifest_has_stronger_provenance",
            )
        )
    return specs


def general_contradiction_specs() -> list[tuple[str, str, str, str, str, str, str, str]]:
    return [
        ("general", "meeting-time-01", "Chat says the review starts at 09:00.", "Calendar invite says the review starts at 10:30.", "When does the review start?", "10:30", "09:00", "calendar_invite_has_higher_corroboration"),
        ("general", "lunch-place-02", "Old note says lunch is at Bento House.", "Confirmed reservation says lunch is at Noodle Bar.", "Where is lunch?", "Noodle Bar", "Bento House", "reservation_beats_old_note"),
        ("general", "office-floor-03", "Draft map says the team sits on floor 4.", "Facilities ticket says the team moved to floor 6.", "Which floor does the team sit on?", "floor 6", "floor 4", "facilities_ticket_beats_draft_map"),
        ("general", "expense-owner-04", "Chat says expenses go to Alex.", "Finance policy says expenses go to Ren.", "Who handles expenses?", "Ren", "Alex", "finance_policy_beats_chat"),
        ("general", "wifi-network-05", "Sticky note says use GuestNet.", "IT bulletin says use CorpNet-2026.", "Which Wi-Fi network should be used?", "CorpNet-2026", "GuestNet", "it_bulletin_beats_sticky_note"),
        ("general", "key-pickup-06", "Message says keys are at reception.", "Building notice says keys are at security desk.", "Where are keys picked up?", "security desk", "reception", "building_notice_beats_message"),
        ("general", "training-room-07", "Spreadsheet says training is in Room 12.", "Instructor note says training is in Room 18.", "Where is training?", "Room 18", "Room 12", "instructor_note_beats_spreadsheet"),
        ("general", "shipping-carrier-08", "Old SOP says ship via ParcelOne.", "Operations update says ship via ShipFast.", "Which carrier is current?", "ShipFast", "ParcelOne", "operations_update_beats_old_sop"),
        ("general", "benefits-link-09", "Bookmark says benefits are at old-benefits.example.", "HR page says benefits are at benefits.example.", "Where is the benefits page?", "benefits.example", "old-benefits.example", "hr_page_beats_bookmark"),
        ("general", "device-owner-10", "Inventory draft says tablet belongs to Casey.", "MDM record says tablet belongs to Robin.", "Who owns the tablet?", "Robin", "Casey", "mdm_record_beats_inventory_draft"),
    ]


def coding_evidence_specs() -> list[tuple[str, str, str, str, str]]:
    return [
        ("coding", f"evidence-service-{index:02d}", f"Service {index} writes audit events before publishing webhooks.", f"What does service {index} do before publishing webhooks?", "writes audit events")
        for index in range(1, 17)
    ] + [
        ("coding", f"evidence-module-{index:02d}", f"Module {index} owns retry budgeting for outbound calls.", f"What does module {index} own?", "retry budgeting for outbound calls")
        for index in range(17, 33)
    ]


def general_evidence_specs() -> list[tuple[str, str, str, str, str]]:
    return [
        ("general", "evidence-general-01", "Nia prefers invoices as PDF attachments.", "How does Nia prefer invoices?", "PDF attachments"),
        ("general", "evidence-general-02", "The office snack order should include decaf tea.", "What should the snack order include?", "decaf tea"),
        ("general", "evidence-general-03", "The team retro uses the blue template.", "Which retro template is used?", "blue template"),
        ("general", "evidence-general-04", "Visitor badges expire after 6 hours.", "When do visitor badges expire?", "6 hours"),
        ("general", "evidence-general-05", "The projector cable lives in drawer B.", "Where is the projector cable?", "drawer B"),
        ("general", "evidence-general-06", "The plant watering rota starts with Uma.", "Who starts the watering rota?", "Uma"),
        ("general", "evidence-general-07", "The workshop uses the west entrance.", "Which entrance does the workshop use?", "west entrance"),
        ("general", "evidence-general-08", "The team lunch budget is 28 dollars per person.", "What is the lunch budget?", "28 dollars per person"),
    ]


def coding_stable_specs() -> list[tuple[str, str, str, str, str]]:
    return [
        ("coding", f"stable-api-{index:02d}", f"The stable health-check path for service {index} is /healthz.", f"What is service {index}'s health-check path?", "/healthz")
        for index in range(1, 9)
    ] + [
        ("coding", f"stable-owner-{index:02d}", f"Component {index} is owned by the platform team.", f"Who owns component {index}?", "platform team")
        for index in range(9, 17)
    ] + [
        ("coding", f"stable-port-{index:02d}", f"Local dev service {index} listens on port {8000 + index}.", f"Which port does local dev service {index} use?", str(8000 + index))
        for index in range(17, 25)
    ]


def general_stable_specs() -> list[tuple[str, str, str, str, str]]:
    return [
        ("general", "stable-general-01", "The reception desk opens at 08:30.", "When does reception open?", "08:30"),
        ("general", "stable-general-02", "The handbook lives at handbook.example.", "Where does the handbook live?", "handbook.example"),
        ("general", "stable-general-03", "The emergency assembly point is Courtyard B.", "Where is the assembly point?", "Courtyard B"),
        ("general", "stable-general-04", "The mailroom code is 2468.", "What is the mailroom code?", "2468"),
        ("general", "stable-general-05", "The support desk closes at 18:00.", "When does support close?", "18:00"),
        ("general", "stable-general-06", "The visitor Wi-Fi password hint is blue-river.", "What is the visitor Wi-Fi password hint?", "blue-river"),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
