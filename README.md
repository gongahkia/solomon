<!-- SPDX-License-Identifier: Apache-2.0 -->

# Solomon

Solomon is a good-law engine for a firm's own knowledge. It tracks whether internal positions, clauses,
house views, notes, and prior advice are still live, what they depend on, and why re-verification is due,
while keeping firm knowledge behind a Kaypoh sanitisation boundary.

Solomon is expected to live at `./solomon/` beside an untouched Kaypoh checkout at `../kaypoh/`.
Solomon may import Kaypoh's Python client from `../kaypoh/src/kaypoh/client.py` or call a running
Kaypoh service, but it does not modify Kaypoh source.

## Triad

| Project | Question | Memory stance | Solomon relationship |
|---|---|---|---|
| Kaypoh | What is safe to let leave the building? | Stateless boundary | Solomon calls its review, pseudonymize, reidentify, and document scrub endpoints. |
| Shibahama | What is worth remembering? | Adaptive decay | Solomon rejects decay for law-firm knowledge because old does not mean stale. |
| Solomon | Is what we know still true, and can we prove it? | Permanent, bi-temporal, currency-aware | This repo. |

## Architecture

Solomon is a Python 3.10+ `uv` project with a FastAPI service, Pydantic v2 schemas, a bi-temporal
knowledge store, a dependency graph, a currency engine, a credence ledger, a retrieval orchestrator,
a metadata-only audit journal, and a Kaypoh boundary adapter.

The first invariant is conservative: Solomon flags moved dependencies and stale verification, but it
does not adjudicate whether a legal position is wrong. A human reviewer decides; Solomon preserves the
evidence chain.

```text
Lawyer query
  -> Solomon recall/evaluate/why API
  -> bi-temporal knowledge store + dependency graph + credence policy
  -> Kaypoh pseudonymize before model egress
  -> remote ZDR or local model endpoint, chosen by sensitivity policy
  -> Kaypoh reidentify with volatile mapping
  -> metadata-only audit journal
```

## Install

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src tests scripts
```

Kaypoh integration expects a sibling checkout:

```bash
cd ..
git clone <kaypoh-repo-url> kaypoh
cd solomon
uv run python scripts/kaypoh_smoke.py --base-url http://127.0.0.1:8131
```

The smoke command assumes Kaypoh is already running. CI starts Kaypoh local from the sibling checkout
before running the smoke script.

## API

The service entry point is `solomon.api.app:create_app`.

```bash
uv run uvicorn solomon.api.app:create_app --factory --host 127.0.0.1 --port 8140
```

Initial health endpoints:

- `GET /health`
- `GET /ready`
- `GET /diagnostics`

Product verbs are reserved around the public contract in `TODO.md`: `ingest`, `recall`,
`evaluate_currency`, `record_verification`, `register_authority_change`, `impact_query`, `why`, and
`timeline`.

## Development Discipline

- Solomon code is Apache-2.0 and carries SPDX headers.
- Kaypoh is a read-only sibling dependency.
- Ruff, mypy, and pytest run in CI with warnings treated as failures.
- Audit logs are metadata-only by design; model prompts must be Kaypoh-sanitised before egress.

