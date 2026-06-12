<!-- SPDX-License-Identifier: Apache-2.0 -->

# Solomon

![Stale house-view demo](docs/assets/stale-house-view-demo.gif)

Solomon is a good-law engine for a firm's own knowledge. It tracks whether internal positions, clauses,
house views, notes, and prior advice are still live, what they depend on, and why re-verification is due,
while keeping firm knowledge behind a Kaypoh zero-retention boundary.

The wedge is simple: every law firm checks whether a published case is still good law; very few systems
check whether the firm's own knowledge is still good law. Current legal KM products are strong at search,
tagging, precedent retrieval, and workflow. Solomon adds temporal truth: dependency edges, supersession,
credence, verification, and an audit trail.

## Why Now

Legal AI adoption is now mainstream, while courts keep seeing hallucinated or stale citations. Damien
Charlotin's public tracker is one of the core references for AI hallucination decisions, and 2026 legal
coverage reports more than a thousand documented incidents globally. At the same time, legal KM remains
framed around surfacing and reusing knowledge assets, not proving whether an internal memo still holds.

Sources:

- Damien Charlotin, [AI Hallucination Cases Database](https://www.damiencharlotin.com/hallucinations/)
- Legaltech Hub, [Knowledge Management overview](https://www.legaltechnologyhub.com/topics/knowledge-management/)
- Clio, [Legal Knowledge Management AI](https://www.clio.com/resources/ai-for-lawyers/legal-knoweldge-management-ai/)
- The Guardian, [AI hallucinations found in high-profile Wall Street law firm filing](https://www.theguardian.com/technology/2026/apr/22/ai-hallucinations-found-in-high-profile-wall-street-law-firm-filing)

## The Triad

| Project | Question | Memory stance | Solomon relationship |
|---|---|---|---|
| Kaypoh | What is safe to let leave the building? | Stateless boundary | Solomon vendors the local `/review`, `/pseudonymize`, `/reidentify`, and `/documents/scrub` surfaces it calls. |
| Shibahama | What is worth remembering? | Adaptive decay | Solomon rejects decay because old legal knowledge is not automatically stale. |
| Solomon | Is what we know still true, and can we prove it? | Permanent, bi-temporal, currency-aware | This repo. |

Solomon is self-contained. The local boundary engine under `src/solomon/boundary/engine/` is vendored from
Kaypoh commit `7415069e57d69398e2c44ef6ababafb0c04a988b`; no sibling `../kaypoh` checkout is required.

## Architecture

```text
Lawyer / API / CLI
  -> ingest / recall / why / timeline
  -> bi-temporal SQLite event store
  -> dependency graph and currency engine
  -> credence ledger and verification guard
  -> vendored Kaypoh-derived boundary for ingest and model-bound context
  -> local model or remote ZDR endpoint by sensitivity policy
  -> hash-chained metadata-only audit journal
```

Core invariants:

- Supersede, never delete, knowledge items.
- Live items are returned by default; stale and superseded items require review mode or explicit queries.
- Solomon flags moved dependencies; it does not adjudicate the law.
- `ModelInferred` content cannot outrank firm-authoritative content as a settled answer.
- Kaypoh mappings are volatile and flushed after reidentification.
- Audit logs store metadata and hashes, not privileged prompt content.

## Demo

Run the headline scenario:

```bash
uv run python examples/stale-house-view/run.py
```

The scenario creates a 2023 house-view memo that depends on Regulation R section 12, registers a 2025
authority change, and shows the 2026 query outcome:

- Warehouse baseline: returns the memo with no staleness signal.
- Solomon: returns the memo flagged `StalePendingReverification`, with the dependency reason.
- Boundary assertion: the model-facing prompt contains `[CLIENT_1]`, not the client identity.

## Install And Verify

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src tests scripts examples/stale-house-view/run.py benchmarks/performance_budget.py
uv run pytest
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

## Honest Limitations

- External monitoring is intentionally narrow: deterministic fixture replay and structured feeds, not
  Shepard's-scale live source coverage.
- The default local retrieval index is deterministic and lightweight; production semantic backends can be
  swapped in.
- Solomon does not decide whether a legal position is wrong. It flags re-verification triggers.
- Boundary correctness depends on Kaypoh's detection and tokenization behavior.

## Documentation

- [Architecture](docs/architecture.md)
- [Concepts](docs/concepts.md)
- [Kaypoh integration](docs/kaypoh-integration.md)
- [Threat model](docs/threat-model.md)
- [Benchmarks](docs/benchmarks.md)
- [ADRs](docs/adr/README.md)
