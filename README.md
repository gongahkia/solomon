# Solomon
<!-- mcp-name: io.github.gongahkia/solomon -->

<p align="center">
  <img src="./docs/assets/stale-house-view-demo.gif" width="75%" alt="Solomon stale house-view demo">
</p>

<p align="center">
  <a href="https://github.com/gongahkia/solomon/actions/workflows/ci.yml"><img alt="ci" src="https://img.shields.io/github/actions/workflow/status/gongahkia/solomon/ci.yml?branch=main&style=flat-square"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square">
  <img alt="api" src="https://img.shields.io/badge/API-FastAPI-009688?style=flat-square">
  <img alt="runtime" src="https://img.shields.io/badge/runtime-offline--default-lightgrey?style=flat-square">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square">
</p>

**MCP-native currency infrastructure for verified legal knowledge.**

Solomon tracks whether internal positions, clauses, house views, notes, and prior advice are still live,
what they depend on, and why re-verification is due. It keeps firm knowledge behind a vendored
Solomon zero-retention boundary and records a metadata-only audit trail for provenance, currency,
credence, verification, deterministic primitive plans, and contestability.

## Table of Contents

- [MCP Quick Start](#mcp-quick-start)
- [Curator Console](#curator-console)
- [CLI And SDK](#cli-and-sdk)
- [Boundary And Memory](#boundary-and-memory)
- [Audit Evidence](#audit-evidence)
- [Development & Evaluation](#development--evaluation)
- [What Solomon Does](#what-solomon-does)
- [API Surface](#api-surface)
- [Examples](#examples)
- [How It Works](#how-it-works)
- [Regulator-ready by construction](#regulator-ready-by-construction)
- [Runtime Modes](#runtime-modes)
- [Documentation](#documentation)
- [Packaging & Deployment](#packaging--deployment)
- [Screenshots](#screenshots)
- [License](#license)

## MCP Quick Start

Install dependencies:

```bash
uv sync --extra dev
```

Check the stdio server:

```bash
uv run solomon mcp serve --help
```

For Claude Desktop, add the following server after replacing `/absolute/path/to/solomon`:

```json
{
  "mcpServers": {
    "solomon": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/solomon",
        "run",
        "solomon",
        "mcp",
        "serve"
      ]
    }
  }
}
```

Detailed host setup, seed data, and a smoke prompt: [`docs/mcp/install.md`](./docs/mcp/install.md).

## Curator Console

Run the thin curator console for dependency review, verification, and audit-pack inspection:

```bash
uv run solomon console serve --host 127.0.0.1 --port 8150
```

See [`docs/console/`](./docs/console/) for supported workflows and screenshots.

Watch the [narrated five-minute tour](./docs/assets/solomon-five-minute-tour.mp4) with
[WebVTT chapter captions](./docs/assets/solomon-five-minute-tour.vtt).

## CLI And SDK

### Power users / dev loop

Use the CLI to seed data, inspect state, or run the local verification loop:

```bash
uv run solomon diagnostics
uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1
uv run solomon dependency-suggestions
uv run solomon recall "structure X regulation"
```

The Python and TypeScript client quickstarts are in [`docs/sdk/`](./docs/sdk/).

## What Solomon Does

- Stores firm knowledge as bi-temporal `KnowledgeItem` records with provenance, source-derived credence,
  matter/client scope, verification metadata, and supersession links.
- Tracks dependency edges between internal knowledge and external authorities, then propagates
  `StalePendingReverification` through transitive dependents when a dependency changes.
- Creates a durable dependency-review queue from deterministic citation/reference extraction, with optional
  Solomon-sanitized LLM assistance for curator confirmation.
- Recalls live knowledge by default while preserving stale, superseded, retired, and contested items for
  review and historical reconstruction.
- Keeps model-bound context behind the Solomon boundary for review, pseudonymization,
  reidentification, document scrubbing, and fail-closed policy.
- Routes strict and zero-egress matters to local-only model execution, with remote ZDR endpoints available
  only when deployment policy explicitly permits them.
- Exposes deterministic primitive plans so an LLM may propose a plan, but Solomon validates and executes
  currency, impact, timeline, verification, and explanation steps deterministically.
- Records metadata-only audit evidence with hash chaining, tamper verification, audit-pack export,
  prompt hashes, endpoint decisions, verification events, primitive-plan hashes, and boundary metadata.
- Provides first-class contestability: `contest`, `affirm`, and `pin` preserve challenges, quarantined
  corrections, partner affirmations, and firm-authoritative credence floors.

Solomon is not a legal-advice product, a general DMS, or a live Shepard's-scale authority monitor. It flags
moved dependencies and overdue verification. It does not decide whether a legal position is wrong.

## API Surface

Runtime and diagnostics:

- `GET /health`
- `GET /diagnostics`
- `GET /tenants`
- `POST /tenants`
- `POST /tenants/{tenant_id}/suspend`
- `POST /tenants/{tenant_id}/reactivate`
- `GET /service-principals`
- `POST /service-principals`
- `POST /service-principals/{principal_id}/rotate`
- `POST /service-principals/{principal_id}/revoke`

Knowledge, recall, and answers:

- `POST /ingest`
- `POST /recall`
- `POST /answer`
- `GET /why/{item_id}`
- `POST /timeline`
- `POST /plans/execute`

Currency, dependency, and references:

- `GET /currency/{item_id}`
- `POST /verification/{item_id}`
- `POST /authorities/{authority_id}/changes`
- `POST /dependencies`
- `POST /dependencies/suggest`
- `GET /dependencies/suggestions`
- `POST /dependencies/suggestions/{suggestion_id}/confirm`
- `POST /dependencies/suggestions/{suggestion_id}/reject`
- `GET /impact/{authority_id}`
- `GET /graph`
- `POST /references/extract`
- `POST /staleness/predict`

Contestability:

- `POST /contest/{item_id}`
- `POST /affirm/{item_id}`
- `POST /pin/{item_id}`

Generated API artifact:

- [`docs/api/openapi.json`](./docs/api/openapi.json)

Regenerate it from the live application:

```bash
uv run python scripts/export_openapi.py
```

## Examples

Ingest and recall through HTTP:

```bash
curl -X POST http://127.0.0.1:8140/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Structure X relies on Regulation R section 12.",
    "kind": "house-view",
    "source_kind": "partner",
    "source_ref": "memo-1",
    "author": "Partner A"
  }'

curl -X POST http://127.0.0.1:8140/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "structure X regulation"}'
```

Execute a deterministic primitive plan:

```bash
curl -X POST http://127.0.0.1:8140/plans/execute \
  -H "Content-Type: application/json" \
  -d '{
    "steps": [
      {"name": "recall", "arguments": {"query": "structure X regulation"}},
      {"name": "impact_query", "arguments": {"authority_id": "Regulation R section 12"}}
    ]
  }'
```

Contest a knowledge item:

```bash
curl -X POST http://127.0.0.1:8140/contest/item-1 \
  -H "Content-Type: application/json" \
  -d '{
    "lawyer_id": "Associate A",
    "actor_tier": "Verified",
    "reason": "Authority treatment needs partner review",
    "proposed_correction": "Updated view after Regulation R section 12 amendment."
  }'
```

Use the Python client:

```python
from solomon.client import SolomonClient

with SolomonClient("http://127.0.0.1:8140") as client:
    item = client.ingest(
        {
            "content": "Structure X relies on Regulation R section 12.",
            "kind": "house-view",
            "source_kind": "partner",
            "source_ref": "memo-1",
            "author": "Partner A",
        }
    )
    results = client.recall({"query": "structure X regulation"})
    why = client.why(item["id"])
    print(results)
    print(why)
```

Included scenarios:

- [`examples/scenarios/01-vendor-integration/`](./examples/scenarios/01-vendor-integration/): a fictional MCP host
  compares stale-text reuse against deterministic preflight and currency checks.
- [`examples/scenarios/stale-house-view/`](./examples/scenarios/stale-house-view/): a 2023 memo becomes stale after a 2025
  authority change; the warehouse baseline misses it.
- [`examples/scenarios/currency-report/`](./examples/scenarios/currency-report/): the same currency signal rendered as a
  partner-facing period report.
- [`examples/scenarios/internal-supersession/`](./examples/scenarios/internal-supersession/): a 2024 position supersedes a
  2022 position while the older item remains available for review and audit.

## How It Works

Solomon has seven main runtime pieces:

1. The FastAPI service in [`src/solomon/api/`](./src/solomon/api/) exposes ingest, recall, answer,
   currency, verification, dependency, timeline, primitive-plan, tenant, and contestability endpoints.
2. The append-only store in [`src/solomon/store/`](./src/solomon/store/) supports SQLite by default and
   Postgres for server deployments, with current-state projection and historical `as_of` reads.
3. The dependency graph in [`src/solomon/graph/`](./src/solomon/graph/) records external, internal, and
   supersession edges, then propagates stale flags through dependents.
4. The currency engine in [`src/solomon/currency/`](./src/solomon/currency/) evaluates live, stale,
   superseded, retired, and verification-aged states without using age-based decay as a proxy for truth.
5. The credence layer in [`src/solomon/credence/`](./src/solomon/credence/) keeps model-inferred content
   below firm-authoritative content for load-bearing answers.
6. The boundary in [`src/solomon/boundary/`](./src/solomon/boundary/) runs Solomon review,
   pseudonymization, reidentification, document scrub, jurisdiction packs, and fail-closed model-egress
   checks.
7. The audit layer in [`src/solomon/audit/`](./src/solomon/audit/) writes a metadata-only hash-chained
   journal and exports verifiable audit packs.

Core flow:

```mermaid
flowchart TD
    Host[MCP host] --> MCP[Solomon MCP server]
    Lawyer[Curator] --> Console[Curator console]
    Operator[Power user] --> CLI[CLI]
    MCP --> Service[Solomon service]
    Console --> Service
    CLI --> Service
    Service --> Boundary[Solomon boundary]
    Boundary --> Store[Bi-temporal event store]
    Store --> Graph[Dependency graph]
    Graph --> Engine[Currency engine]
    Engine --> Context[Current context / why / impact]
    Context --> Plan[Deterministic primitive plan]
    Plan --> Model{Model needed}
    Model -->|local or approved ZDR| Answer[Host answer with evidence]
    Service --> Audit[Metadata-only audit journal]
    Plan --> Audit
```

Core invariants:

- Supersede, never delete, knowledge items.
- Old is not stale; dependency movement, supersession, retirement, verification age, or contest signals
  drive currency.
- Live items are returned by default; stale and superseded items require review mode or explicit queries.
- The LLM never decides currency, supersession, verification, impact, timeline, or contest promotion.
- `ModelInferred` content cannot outrank `FirmAuthoritative` content as a settled answer.
- Boundary mappings are volatile and flushed after reidentification.
- Audit logs store metadata and hashes, not privileged prompt content.

## Audit Evidence

Solomon records a metadata-only, hash-chained audit journal. An audit pack binds the primitive plan,
provenance, currency state, verification events, boundary decision metadata, and tamper-verification result
needed to reconstruct what Solomon did without retaining privileged prompt content. See
[`docs/release-artifacts.md`](./docs/release-artifacts.md) and [`docs/regulatory-evidence.md`](./docs/regulatory-evidence.md).

## Backup And Recovery

SQLite deployments can create an encrypted archive of every local durable database and the audit journal. The
passphrase is read only from `SOLOMON_BACKUP_PASSPHRASE`; retain both the archive and its adjacent manifest.

```bash
export SOLOMON_BACKUP_PASSPHRASE='store-this-outside-the-deployment'
uv run solomon backup ./solomon-backup.enc
uv run solomon recovery-drill ./solomon-backup.enc
uv run solomon restore ./solomon-backup.enc ./restored-deployment
```

`restore` rejects an existing target and writes `data/` and `journal/` below the supplied deployment root. Point a
fresh deployment at those paths with `SOLOMON_DATA_DIR` and `SOLOMON_JOURNAL_DIR`. `recovery-drill` restores to a
temporary fresh deployment, checks every SQLite database, initializes the local service, and verifies the audit
journal. Run backups during a brief writer quiescence when cross-database point-in-time consistency is required.
The commands intentionally reject Postgres deployments; use a database-native Postgres backup until a
coordinated server-storage backup contract is available.

## Prometheus Metrics

Every FastAPI deployment exposes unauthenticated Prometheus text metrics at `GET /metrics` for its scrape target.
The endpoint exports health, durable queue/dead-letter depth, review-task state, latest source-sync state, HTTP and
scrape latency histograms, retrieval volume, and currency-state context withholding. It intentionally excludes
tenant IDs, client IDs, matter IDs, source references, query text, and document content from metric labels.

```bash
curl -fsS http://127.0.0.1:8140/metrics
```

The exporter is process-local and uses the open-source `prometheus-client` library; it needs no managed observability
vendor. Scrapes use SQL aggregate gauges, and audit-journal verification is cached for 30 seconds.

## End-to-End Evaluation

[`docs/evaluation-corpus.e2e.synthetic.json`](./docs/evaluation-corpus.e2e.synthetic.json) is a public, versioned,
synthetic corpus for source ingestion, candidate promotion, authority impact, human review, and MCP-preflight
outcomes. The harness reports extraction precision/recall, graph-impact recall, stale-context leakage, review
completion, and post-review MCP context recall.

```bash
uv run python scripts/evaluate_end_to_end.py --output ./artifacts/end-to-end-evaluation.json
```

## Pilot-Readiness Gates

Release verification runs security, local recall-performance, encrypted-restore, source/review workflow, and
MCP unsafe-reuse gates. It emits a self-hosted JSON report and exits nonzero when any selected gate fails.

```bash
uv run python scripts/release_quality_gates.py --output ./artifacts/release-quality-gates.json
```

## Regulator-ready by construction

Every model-backed answer carries a reproducible primitive plan, source provenance, currency state,
verification status, dependency context, boundary metadata, and visible contest history. The `why` and
audit-pack paths turn those fields into evidence about what Solomon did, why it did it, on what basis, and
which human or system actor was accountable.

Solomon produces evidence about its own reasoning and currency. It does not certify legal compliance,
decide the law, or replace the firm's instructions-for-use, human oversight, or regulator-facing review
process. See [`docs/regulatory-evidence.md`](./docs/regulatory-evidence.md).

## Boundary And Memory

Solomon owns both the zero-retention boundary and the currency engine. The boundary answers what can be
reviewed, pseudonymized, reidentified, scrubbed, or sent to a model. The currency engine answers whether
internal knowledge is live, stale-pending-reverification, superseded, or retired.

Solomon is self-contained. The local boundary engine under [`src/solomon/boundary/engine/`](./src/solomon/boundary/engine/)
requires no sibling checkout.

Select the supported boundary profile (`sg`, `my`, `uk`, or `eu`) through `SOLOMON_JURISDICTION`, or for a single
operation with `--jurisdiction`:

```bash
uv run solomon ingest "memo text" --source-ref memo-1 --jurisdiction uk
uv run solomon mcp serve --http --jurisdiction uk
uv run solomon console serve --jurisdiction uk
```

The profile sets both default source and destination jurisdictions. It is a detector-routing setting, not a legal
classification or compliance switch.

## Runtime Modes

### Local SKU

`solomon-local` is offline-default. It uses SQLite, the in-process Solomon boundary, deterministic
hashed retrieval embeddings, and local-only model routing unless deployment policy explicitly enables
remote egress.

It must not require:

```text
postgres, redis, external HTTP, remote model credentials
```

Build the local binary:

```bash
uv sync --extra packaging
uv run pyinstaller packaging/solomon-local.spec --noconfirm --clean
./dist/solomon-local --version
```

### Server SKU

`solomon-server` enables API-key auth, tenant isolation, optional Postgres storage, and optional remote
ZDR model routing.

Server deployments should configure OIDC. A server with only `SOLOMON_SERVER_API_KEY` uses the retained
legacy API-key compatibility path; set `SOLOMON_SERVER_AUTH_MODE=legacy-api-key` explicitly during migration.

Run a local server:

```bash
SOLOMON_SKU=server \
SOLOMON_SERVER_API_KEY=change-me \
uv run uvicorn solomon.api.app:create_app --factory --host 0.0.0.0 --port 8140
```

Enable Postgres storage:

```bash
uv sync --extra server

SOLOMON_SKU=server \
SOLOMON_SERVER_API_KEY=change-me \
SOLOMON_DATABASE_URL=postgresql://solomon:solomon@localhost:5432/solomon \
uv run uvicorn solomon.api.app:create_app --factory --host 0.0.0.0 --port 8140
```

OIDC is server-only and requires an HTTPS issuer, audience, and explicit JSON claim mapping. This example maps
the IdP's `roles` values to Solomon roles; unmatched or malformed values are denied.

```bash
SOLOMON_OIDC_ISSUER=https://idp.example \
SOLOMON_OIDC_AUDIENCE=solomon-api \
SOLOMON_OIDC_ROLE_CLAIM=roles \
SOLOMON_OIDC_ROLE_MAPPINGS='{"firm-admin":"admin","firm-lawyer":"lawyer","connector":"integration"}'
```

Envelope-encrypt source-document and candidate-claim content at rest by supplying a non-secret key reference and a
Base64-encoded 32-byte AES-256 key through the deployment secret manager. The key value is not included in diagnostics
or audit records.

```bash
SOLOMON_CONTENT_ENCRYPTION_KEY_REF='kms://firm-keyring/solomon-content/v1' \
SOLOMON_CONTENT_ENCRYPTION_KEY="$(openssl rand -base64 32)" \
uv run uvicorn solomon.api.app:create_app --factory --host 0.0.0.0 --port 8140
```

Changing the reference or key prevents startup from reading existing encrypted content; restore the matching key
before rotating data through an approved migration.

Create tenant-bound integration credentials with an admin principal. The generated credential is shown only on
creation or rotation; keep it in a secret manager. Solomon stores only a PBKDF2-SHA256 hash, requires the bound
`x-tenant-id` on each request, enforces its configured scopes, and denies it after revocation.

```bash
curl -X POST http://localhost:8140/service-principals \
  -H 'x-api-key: change-me' \
  -H 'content-type: application/json' \
  -d '{"principal_id":"document-connector","tenant_id":"tenant-a","scopes":["tenant:read"]}'

curl -X POST http://localhost:8140/recall \
  -H 'x-api-key: <generated-credential>' \
  -H 'x-tenant-id: tenant-a' \
  -H 'content-type: application/json' \
  -d '{"query":"contract renewal"}'
```

Postgres retrieval requires the self-hosted `pgvector` extension. Startup runs `CREATE EXTENSION IF NOT EXISTS vector`,
validates it, and applies the transactional `vector(256)`/HNSW migration; the database role therefore needs that
extension installed and creation privilege.

Remote model egress requires explicit configuration:

```bash
SOLOMON_ZERO_EGRESS_MODE=false \
SOLOMON_ALLOW_REMOTE_EGRESS=true \
SOLOMON_REMOTE_MODEL_URL=https://example.invalid/v1/responses
```

Retrieval remains on the pinned local hashed embedding provider by default. Remote OpenAI-compatible embeddings are a
separate server-only opt-in; `SOLOMON_ALLOW_REMOTE_EMBEDDING_EGRESS=true` requires zero-egress mode disabled plus an
embeddings endpoint and API key. The key is not emitted in diagnostics.

### Docker

`docker-compose.server.yml` is the canonical development deployment for the server SKU. It mounts the checkout and
keeps SQLite data and audit journals in named volumes; use it for the documented local server loop rather than
maintaining a parallel Compose file.

```bash
SOLOMON_SERVER_API_KEY=change-me docker compose -f docker-compose.server.yml up --build
curl -H 'Authorization: Bearer change-me' http://localhost:8140/health
```

## Documentation

- [`docs/architecture.md`](./docs/architecture.md): service architecture, deterministic primitive plans,
  contestability, storage, tenancy, auth, boundary, and reference extraction.
- [`docs/console/`](./docs/console/): curator console screens, screenshots, GIFs, and stack decision.
- [`docs/concepts.md`](./docs/concepts.md): currency, bi-temporality, dependency graph, credence, and
  verification concepts.
- [`docs/boundary-integration.md`](./docs/boundary-integration.md): Solomon boundary behavior.
- [`docs/trust-boundary.md`](./docs/trust-boundary.md): model egress, pseudonymization, contestability,
  and fail-closed trust-boundary rules.
- [`docs/regulatory-evidence.md`](./docs/regulatory-evidence.md): evidence mapping for EU AI Act,
  NIST AI RMF, ISO/IEC 42001, and multi-jurisdiction review needs.
- [`docs/threat-model.md`](./docs/threat-model.md): threats, controls, residual risks, and deployment
  assumptions.
- [`docs/known-limitations.md`](./docs/known-limitations.md): current monitoring, retrieval, boundary,
  and legal-adjudication limits.
- [`docs/positioning.md`](./docs/positioning.md): partner-facing product narrative.
- [`docs/one-pager.md`](./docs/one-pager.md): portfolio-review summary, with a rendered PDF in `output/pdf/`.
- [`docs/benchmarks.md`](./docs/benchmarks.md): currency and retrieval evaluation results.
- [`docs/release-artifacts.md`](./docs/release-artifacts.md): v0.1.0 artifact hashes and release evidence.
- [`docs/api/openapi.json`](./docs/api/openapi.json): generated OpenAPI contract.
- [`docs/cli-mcp-verb-audit.md`](./docs/cli-mcp-verb-audit.md): CLI names aligned to MCP tool names.
- [`docs/sdk/`](./docs/sdk/): Python and TypeScript SDK quickstarts.
- [`docs/adr/README.md`](./docs/adr/README.md): architecture decision records.

## Development & Evaluation

Install development dependencies:

```bash
uv sync --extra dev
```

Run lint and type checks:

```bash
uv run ruff check .
uv run mypy src/solomon
```

Run the full test suite:

```bash
uv run pytest
```

Run production-confidence checks:

```bash
uv run pytest tests/test_boundary_accuracy.py
SOLOMON_TEST_POSTGRES_DSN=postgresql://solomon:solomon@localhost:5432/solomon \
  uv run pytest -m integration tests/test_postgres_live_integration.py
```

Run the performance gate:

```bash
uv run python benchmarks/performance_budget.py
```

Run the headline demo:

```bash
uv run python examples/scenarios/stale-house-view/run.py
```

Regenerate README media and API artifacts:

```bash
uv run python scripts/render_stale_house_view_gif.py
uv run python scripts/render_console_gifs.py
uv run python scripts/render_vendor_integration_gif.py
uv run python scripts/export_openapi.py
```

## Packaging & Deployment

Build pip-installable artifacts:

```bash
uv build
```

Build the local binary:

```bash
uv sync --extra packaging
uv run pyinstaller packaging/solomon-local.spec --noconfirm --clean
```

Expected outputs:

- `dist/solomon-0.1.0.tar.gz`
- `dist/solomon-0.1.0-py3-none-any.whl`
- `dist/solomon-local`

Package surfaces:

- [`packaging/solomon-local.spec`](./packaging/solomon-local.spec): PyInstaller entry for the offline
  local SKU.
- [`docker-compose.server.yml`](./docker-compose.server.yml): server SKU Compose entry.
- [`packaging/README.md`](./packaging/README.md): release artifact build notes.

## Screenshots

### Verification Desk

![Verification Desk](./docs/assets/console/verification-desk.png)

### Dependency Review

![Dependency Review](./docs/assets/console/dependency-review.png)

### Audit Pack

![Audit Pack](./docs/assets/console/audit-pack.png)

Animated walkthroughs live beside the PNGs in [`docs/assets/console/`](./docs/assets/console/).

## License

Apache-2.0. See [`LICENSE`](./LICENSE).
