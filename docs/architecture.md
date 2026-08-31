<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture

Solomon is a Python 3.10+ FastAPI service and CLI. It is organized around durable currency evidence:

- `currency`: data models, currency evaluation, feeds, reports, and supersession proposals.
- `store`: SQLite event store, backend factory, encrypted artifacts.
- `graph`: bi-temporal dependency edges, propagation, and suggestions.
- `credence`: source-tier policy, load-bearing guardrails, prompt-context separation.
- `boundary`: Solomon review, pseudonymize, reidentify, scrub, and fail-closed policy.
- `orchestrator`: retrieval and model routing.
- `audit`: hash-chained metadata-only journal and audit-pack export.
- `api` and `cli`: public verbs.

## Request Lifecycle

1. Ingest creates a `KnowledgeItem` with provenance and source-derived credence.
2. The Solomon boundary review engine gates storage before the item is written.
3. Local deterministic extraction finds cited reliance candidates after boundary preflight. Suggestions retain source
   spans and remain pending until a curator confirms them; only then does Solomon create a dependency edge.
4. Authority changes propagate staleness through graph dependents.
5. Recall searches the local index, filters Live items by default, expands dependencies, and applies credence.
6. Model context is pseudonymized by the configured boundary before any remote endpoint.
7. The audit journal records metadata-only evidence.

## Store

SQLite is the local default. Server deployments can set `SOLOMON_DATABASE_URL` to a `postgres://` or
`postgresql://` DSN and install the optional `solomon[server]` dependency for the psycopg driver. Both
backends preserve the same event-log contract: knowledge is written through append-only events and projected
into current state, dependency edges are bi-temporal, and the retrieval index stores deterministic hashed
vectors. Postgres stores these as `pgvector` `vector(256)` values, with a transactional backfill migration and
HNSW cosine index; deployments must install the self-hosted extension and grant the startup role `CREATE EXTENSION`.
Postgres retrieval joins the tenant knowledge projection before full-text and vector candidate ranking, then fuses
those scoped candidates with the same currency and credence controls used locally.
Supersession closes `valid_to`, links the successor, and leaves the predecessor queryable in review or historical modes.

In server mode, tenants are tracked in a durable registry at `data_dir/tenants/registry.json`. Admin requests
can create, list, suspend, and reactivate tenants through `/tenants`, `/tenants/{tenant_id}/suspend`, and
`/tenants/{tenant_id}/reactivate`. Tenant records include lifecycle state and optional tenant-specific API
key hashes; raw tenant keys are not stored. `SOLOMON_SERVER_AUTO_PROVISION_TENANTS=false` disables implicit
first-request tenant creation and requires pre-registration.

Tenant storage stays isolated after registry admission. SQLite deployments use per-tenant data and journal
directories. When Postgres is configured, each tenant is mapped to a sanitized Postgres schema so tenant data
does not share tables.

Server admins create, list, rotate, and revoke tenant-bound integration service principals through
`/service-principals`. Creation and rotation return a generated credential exactly once; the durable registry stores
only its PBKDF2-SHA256 hash. A service principal presents the credential with `x-api-key` and its bound tenant with
`x-tenant-id`; it cannot authenticate for another tenant. Its explicit scopes are enforced before dispatch, and
authentication plus lifecycle decisions are metadata-only, hash-chained audit entries with actor and correlation ID.

Source-document and candidate-claim content can use envelope encryption when both
`SOLOMON_CONTENT_ENCRYPTION_KEY_REF` and `SOLOMON_CONTENT_ENCRYPTION_KEY` are configured. Solomon generates a
unique AES-256-GCM data-encryption key per content field and wraps it with the configured AES-256 key-encryption key
using AES Key Wrap; the envelope stores the non-secret key reference, wrapped data key, nonce, and ciphertext. The
key value is a Base64-encoded 32-byte secret supplied by the deployment's secret injector and is never written to
diagnostics, audit entries, or the database. Existing plaintext source-document and candidate-claim rows are migrated
when encryption is enabled; unavailable references or authentication failures fail closed. Encryption decisions are
metadata-only audit entries with actor and correlation ID.

Retention is an explicit operator workflow, not an automatic deletion timer. `SOLOMON_RETENTION_DEFAULT_DAYS`
enables `POST /retention/run`; administrators may also create item-, matter-, or client-scoped erasure requests.
An active legal hold matching any target blocks the complete request and records a held state. A completed request
retires each current item and replaces its queryable content with a retention marker, while the append-only event
history remains intact for audit-chain verification. Legal-hold reasons, scope IDs, and subject references are hashed
in audit entries; the durable registry keeps a subject-reference hash, request state, and affected item IDs. Server
retention endpoints require an administrator and an explicit registered `tenant_id`.

Optional OpenTelemetry tracing uses a process-local provider and OTLP/HTTP only when
`SOLOMON_TELEMETRY_ENABLED=true` with `SOLOMON_TELEMETRY_OTLP_ENDPOINT`. The provider is not bound to a managed
vendor. It traces ingestion, source connectors, retrieval, review, boundary review, MCP tools, and webhooks with
operation-level attributes only; raw knowledge, query text, identifiers, credentials, and scope IDs are excluded.

Optional server OIDC authentication requires `SOLOMON_OIDC_ISSUER` and `SOLOMON_OIDC_AUDIENCE`. The issuer must
be HTTPS; Solomon obtains signing keys from its discovery document, caches JWKS entries, refreshes once for an
unknown `kid`, and accepts only RS256 or ES256 JWTs with matching issuer, audience, expiry, and clock-skew checks.
`SOLOMON_OIDC_ROLE_CLAIM` defaults to `roles`, and `SOLOMON_OIDC_ROLE_MAPPINGS` is a required JSON object mapping
exact claim values to `admin`, `curator`, `reviewer`, `lawyer`, or `integration`; unmapped or malformed claims are
denied. Roles resolve in a fixed admin-to-integration precedence and their scopes are combined. OIDC authentication
decisions are hash-chained audit entries with actor ID (when validated), canonical roles, decision, and request
correlation ID; bearer tokens and claim bodies are not recorded.

Authenticated server requests bind their principal and correlation ID to the selected tenant service. Each
content-returning or mutating service operation applies a centralized `read`, `write`, `curate`, or `review` policy
before invoking domain logic, then writes a metadata-only allow/deny audit entry. Curators manage sources and
dependencies; reviewers and lawyers perform verification/contestability actions; integrations remain read-only.

The console uses the same OIDC claim mapping in server mode; its legacy bearer path has an explicitly configured
console identity and role. Sources, claims, and dependencies are curator screens, verification and review actions
are reviewer/lawyer screens, and every console decision records actor, roles, decision, and correlation ID. Local
development retains an in-process admin identity when no console bearer or OIDC configuration is present.

## Server Auth

`solomon-server` requires OIDC issuer/audience/role mapping or the legacy `SOLOMON_SERVER_API_KEY` path. OIDC
servers reject static credentials and map validated bearer tokens to principals. Legacy deployments may present
credentials through `Authorization: Bearer <token>` or `x-api-key`; the server maps those credentials to a principal:

- the server admin key gets `admin:*`, `tenant:manage`, `tenant:read`, `tenant:write`, and `diagnostics:read`;
- tenant keys are stored only as PBKDF2-SHA256 hashes and default to `tenant:read` plus `tenant:write`;
- tenant creation can restrict a key to narrower scopes such as `tenant:read`.
- service-principal credentials are returned only by create or rotate, stored as PBKDF2-SHA256 hashes, and can be
  restricted to explicit tenant scopes; revoked credentials are denied.

Middleware classifies routes before invoking handlers. Tenant management and diagnostics require admin scopes;
tenant read routes such as recall/answer require `tenant:read`; mutating tenant routes such as ingest,
verification, dependency add, and authority changes require `tenant:write`.

## Deterministic Primitive Plans

The core service verbs are also exposed as deterministic primitives through `/plans/execute`. A plan is an
ordered list of sanctioned calls: `recall`, `evaluate_currency`, `impact_query`, `timeline`,
`record_verification`, and `why`. The executor rejects unknown primitive names and validates every step's
arguments with Solomon's typed request models before any side effect occurs.

Plan execution returns the exact validated plan, store-state hash, per-step result hashes, and result summaries.
The audit journal records a metadata-only `primitive_plan` event containing the plan hash, store-state hash,
argument hashes, result hashes, and identifiers surfaced by each step. Answer responses carry the primitive
plan summary used to gather their context, so reviewers can re-run the same plan against the same store state.
LLM output may propose a plan, but currency, impact, timeline, verification, and explanation are resolved by
these deterministic primitives.

## Contestability

Contestability is a first-class service path, not a side note on verification. `contest(item_id, ...)` records
a challenge, demotes the item to `Unverified`, marks it `StalePendingReverification`, preserves contest history
in item metadata, and propagates re-verification to dependents. Proposed corrections are stored as quarantined
low-credence items until a `FirmAuthoritative` actor affirms them.

`affirm(item_id, ...)` lets a FirmAuthoritative actor either reaffirm the contested item or affirm a proposed
correction. Affirming a correction supersedes the contested predecessor without deleting it. `pin(item_id, ...)`
sets a FirmAuthoritative credence floor for positions the firm has deliberately stabilized. Model-inferred or
lower-tier actors can flag contests but cannot override human-affirmed knowledge.

## Reference Extraction

`/references/extract` runs after optional Solomon boundary sanitization. Citation parsing uses `eyecite` for full,
short, statutory, `supra`, and `id.` citation forms, then Solomon's deterministic grammar fills gaps for
firm-style authority references such as "Regulation R section 12", non-US case strings, and defined terms.
Each returned citation includes its parser source and source-text span so reviewers can inspect the exact
evidence before confirming a dependency edge.

Dependency suggestions are now durable review records. Ingest creates deterministic pending suggestions;
`/dependencies/suggest` can re-run extraction and optionally use Solomon-sanitized LLM assistance. Curators can
list, confirm, or reject suggestions through `/dependencies/suggestions`; confirmed suggestions create
`human_confirmed` dependency edges, while rejected suggestions remain review history.

## Boundary

The boundary engine lives under `src/solomon/boundary/engine/`. If that in-process boundary errors, ingestion
and model egress fail closed.
