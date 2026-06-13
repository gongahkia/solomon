# Solomon

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

Currency-aware good-law infrastructure for a firm's own knowledge.

Solomon tracks whether internal positions, clauses, house views, notes, and prior advice are still live,
what they depend on, and why re-verification is due. It keeps firm knowledge behind a vendored
Kaypoh-derived zero-retention boundary and records a metadata-only audit trail for provenance, currency,
credence, verification, deterministic primitive plans, and contestability.

## Table of Contents

- [Quick Start](#quick-start)
- [What Solomon Does](#what-solomon-does)
- [API Surface](#api-surface)
- [Examples](#examples)
- [How It Works](#how-it-works)
- [Regulator-ready by construction](#regulator-ready-by-construction)
- [The Triad](#the-triad)
- [Runtime Modes](#runtime-modes)
- [Documentation](#documentation)
- [Development & Evaluation](#development--evaluation)
- [Packaging & Deployment](#packaging--deployment)
- [Screenshots](#screenshots)
- [License](#license)

## Quick Start

Install dependencies:

```bash
uv sync --extra dev
```

Run the standard verification gate:

```bash
uv run ruff check .
uv run mypy src/solomon
uv run pytest
```

Run the headline stale-house-view scenario:

```bash
uv run python examples/stale-house-view/run.py
```

Start the API:

```bash
uv run uvicorn solomon.api.app:create_app --factory --host 127.0.0.1 --port 8140
```

Use the CLI:

```bash
uv run solomon diagnostics
uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1
uv run solomon recall "structure X regulation"
```

## What Solomon Does

- Stores firm knowledge as bi-temporal `KnowledgeItem` records with provenance, source-derived credence,
  matter/client scope, verification metadata, and supersession links.
- Tracks dependency edges between internal knowledge and external authorities, then propagates
  `StalePendingReverification` through transitive dependents when a dependency changes.
- Recalls live knowledge by default while preserving stale, superseded, retired, and contested items for
  review and historical reconstruction.
- Keeps model-bound context behind the vendored Kaypoh-derived boundary for review, pseudonymization,
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

Knowledge, recall, and answers:

- `POST /ingest`
- `POST /recall`
- `POST /answer`
- `GET /why/{item_id}`
- `POST /timeline`
- `POST /plans/execute`

Currency, dependency, and references:

- `POST /currency/evaluate`
- `POST /verification`
- `POST /authority-change`
- `POST /dependency`
- `POST /impact`
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

- [`examples/stale-house-view/`](./examples/stale-house-view/): a 2023 memo becomes stale after a 2025
  authority change; the warehouse baseline misses it.
- [`examples/internal-supersession/`](./examples/internal-supersession/): a 2024 position supersedes a
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
6. The vendored boundary in [`src/solomon/boundary/`](./src/solomon/boundary/) runs Kaypoh-derived review,
   pseudonymization, reidentification, document scrub, jurisdiction packs, and fail-closed model-egress
   checks.
7. The audit layer in [`src/solomon/audit/`](./src/solomon/audit/) writes a metadata-only hash-chained
   journal and exports verifiable audit packs.

Core flow:

```mermaid
flowchart TD
    Lawyer[Lawyer / API / CLI] --> Ingest[Ingest knowledge]
    Ingest --> Boundary[Kaypoh-derived boundary review]
    Boundary --> Store[Bi-temporal event store]
    Store --> Graph[Dependency graph]
    Graph --> Currency[Currency engine]
    Currency --> Recall[Recall / answer / why]
    Recall --> Plan[Deterministic primitive plan]
    Plan --> Model{Model needed}
    Model -->|local or approved ZDR| Answer[Answer with evidence]
    Recall --> Contest[Contest / affirm / pin]
    Store --> Audit[Metadata-only audit journal]
    Plan --> Audit
    Contest --> Audit
```

Core invariants:

- Supersede, never delete, knowledge items.
- Old is not stale; dependency movement, supersession, retirement, verification age, or contest signals
  drive currency.
- Live items are returned by default; stale and superseded items require review mode or explicit queries.
- The LLM never decides currency, supersession, verification, impact, timeline, or contest promotion.
- `ModelInferred` content cannot outrank `FirmAuthoritative` content as a settled answer.
- Kaypoh mappings are volatile and flushed after reidentification.
- Audit logs store metadata and hashes, not privileged prompt content.

## Regulator-ready by construction

Every model-backed answer carries a reproducible primitive plan, source provenance, currency state,
verification status, dependency context, boundary metadata, and visible contest history. The `why` and
audit-pack paths turn those fields into evidence about what Solomon did, why it did it, on what basis, and
which human or system actor was accountable.

Solomon produces evidence about its own reasoning and currency. It does not certify legal compliance,
decide the law, or replace the firm's instructions-for-use, human oversight, or regulator-facing review
process. See [`docs/regulatory-evidence.md`](./docs/regulatory-evidence.md).

## The Triad

| Project | Question | Memory stance | Solomon relationship |
|---|---|---|---|
| Kaypoh | What is safe to let leave the building? | Stateless boundary | Solomon vendors the local `/review`, `/pseudonymize`, `/reidentify`, and `/documents/scrub` surfaces it calls. |
| Shibahama | What is worth remembering? | Adaptive decay | Solomon rejects decay because old legal knowledge is not automatically stale. |
| Solomon | Is what we know still true, and can we prove it? | Permanent, bi-temporal, currency-aware | This repo. |

Solomon is self-contained. The local boundary engine under [`src/solomon/boundary/engine/`](./src/solomon/boundary/engine/)
is vendored from Kaypoh commit `7415069e57d69398e2c44ef6ababafb0c04a988b`; no sibling `../kaypoh`
checkout is required.

## Runtime Modes

### Local SKU

`solomon-local` is offline-default. It uses SQLite, the in-process Kaypoh-derived boundary, deterministic
hashed retrieval embeddings, and local-only model routing unless deployment policy explicitly enables
remote egress.

It must not require:

```text
postgres, redis, external HTTP, remote model credentials, sibling ../kaypoh checkout
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

Remote model egress requires explicit configuration:

```bash
SOLOMON_ZERO_EGRESS_MODE=false \
SOLOMON_ALLOW_REMOTE_EGRESS=true \
SOLOMON_REMOTE_MODEL_URL=https://example.invalid/v1/responses
```

### Docker

```bash
docker compose -f docker-compose.server.yml up --build
curl http://localhost:8140/health
```

## Documentation

- [`docs/architecture.md`](./docs/architecture.md): service architecture, deterministic primitive plans,
  contestability, storage, tenancy, auth, boundary, and reference extraction.
- [`docs/concepts.md`](./docs/concepts.md): currency, bi-temporality, dependency graph, credence, and
  verification concepts.
- [`docs/kaypoh-integration.md`](./docs/kaypoh-integration.md): vendored Kaypoh boundary provenance and
  integration behavior.
- [`docs/trust-boundary.md`](./docs/trust-boundary.md): model egress, pseudonymization, contestability,
  and fail-closed trust-boundary rules.
- [`docs/regulatory-evidence.md`](./docs/regulatory-evidence.md): evidence mapping for EU AI Act,
  NIST AI RMF, ISO/IEC 42001, and multi-jurisdiction review needs.
- [`docs/threat-model.md`](./docs/threat-model.md): threats, controls, residual risks, and deployment
  assumptions.
- [`docs/known-limitations.md`](./docs/known-limitations.md): current monitoring, retrieval, boundary,
  and legal-adjudication limits.
- [`docs/benchmarks.md`](./docs/benchmarks.md): currency and retrieval evaluation results.
- [`docs/release-artifacts.md`](./docs/release-artifacts.md): v0.1.0 artifact hashes and release evidence.
- [`docs/api/openapi.json`](./docs/api/openapi.json): generated OpenAPI contract.
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

Run the performance gate:

```bash
uv run python benchmarks/performance_budget.py
```

Run the headline demo:

```bash
uv run python examples/stale-house-view/run.py
```

Regenerate README media and API artifacts:

```bash
uv run python scripts/render_stale_house_view_gif.py
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

The README currently embeds the stale-house-view demo GIF from [`docs/assets/`](./docs/assets/).

Useful screenshots to add under `docs/assets/`:

- FastAPI `/docs` showing the active Solomon API surface.
- Example `/recall` result with dependency and currency evidence.
- Example `/plans/execute` response showing deterministic step hashes.
- Example `/contest/{item_id}` response showing visible contest history and quarantined correction.
- Audit-pack verification output.

Once those files exist, this section can embed them with relative links.

## License

Apache-2.0. See [`LICENSE`](./LICENSE).
