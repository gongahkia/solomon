<!-- SPDX-License-Identifier: Apache-2.0 -->

# Currency Loop Proof

## Positioning and user problem

Solomon is **a self-hosted provenance and change-impact control plane for high-stakes AI systems, initially applied to internal legal knowledge.** Its first rigorous vertical is internal legal knowledge because a firm can have a correct historical document that is unsafe to reuse after one of its authorities moves.

The product loop is deliberately narrow: an authority-change signal is recorded, confirmed dependency edges identify directly and transitively affected internal knowledge, affected items are flagged for a human reviewer, and a reviewer reaffirms, supersedes, or retires the item. Default recall withholds non-live items; review mode and `why` make the flag explainable. **Flag, do not adjudicate.**

Solomon is not a citator, document-management system, generic search engine, drafting system, agent-memory store, or legal adjudicator. A citator determines authority treatment; Solomon consumes an authority-change signal and manages the internal impact of that signal. A DMS stores source documents; Solomon stores currency-relevant knowledge records and provenance. Search ranks matches; Solomon gates reuse by temporal validity, dependency impact, credence, and human decisions. Drafting and agent systems may call Solomon, but cannot use it to turn a dependency flag into a legal conclusion.

## Canonical deterministic scenario

`examples/scenarios/currency-loop-proof/run.py` constructs this synthetic fixture without a model call or network request:

| Element | Fixture value | Purpose |
|---|---|---|
| Authority | one synthetic official-gazette section | authority-change trigger |
| Direct dependents | two human-confirmed citation edges | direct impact coverage |
| Transitive dependent | one internal item depending on a direct item | traversal coverage |
| Unrelated item | one item in a separate matter/client scope | false-positive and isolation coverage |
| Scopes | `matter-alpha`/`client-alpha` and `matter-bravo`/`client-bravo` | restricted MCP authorization |
| Cycle probe | a bounded internal dependency cycle in the affected subgraph | traversal termination |
| Human outcomes | two reaffirmations and one supersession to a live successor | recovery and predecessor history |

The semantic result is committed as `tests/fixtures/currency-loop-proof-snapshot.json`. The headless scenario writes a raw machine result with measured local latency and a normalized snapshot. `tests/test_currency_loop_demo.py` compares the normalized snapshot in CI and checks the local 2,000 ms budget. This is a deterministic fixture, not a production-scale benchmark.

## State machine

| Trigger | Stored state | Recall behavior | Required next action |
|---|---|---|---|
| Ingested and verified | `Live` | eligible by default | none |
| Authority event reaches a confirmed dependency | `StalePendingReverification` with a staleness reason and change ID | withheld by default; visible in review mode | assign and resolve review task |
| Reviewer reaffirms | `Live`, fresh verification history | eligible by default | none |
| Reviewer supersedes | predecessor `Superseded`, `valid_to` closed, successor ID retained | predecessor historical/review only; live successor may be recalled | preserve successor evidence |
| Reviewer retires | `Retired`, `valid_to` closed | not recalled by default | retain audit/history |

Authority events are durable in `workflow.sqlite3` under a unique `(source_id, idempotency_key)`. A completed duplicate returns the original event and tasks without re-propagating. An incomplete event is retried: propagation carries the persistent authority-event ID as `change_id`, so a replay will continue any unfinished traversal while avoiding duplicate stale-item events, review tasks, and impact audit entries. Authority polling has bounded retry/backoff, a visible dead-letter queue, and an explicit requeue action. These are delivery controls, not proof that an upstream authority feed is complete or correct.

## Security and evidence boundaries

- MCP principals with restricted matter/client allowlists are denied before a mismatched tool call returns results. Scoped recall filters candidates before fusion; scoped MCP impact results filter affected items to the requested permitted scope. Historical timeline recall now applies the same matter/client filtering.
- Confirmed edges record human confirmation, actor, reason, and source relationship. Citation extraction may suggest edges, but the scenario uses human-confirmed edges and never treats an extraction or model output as authoritative.
- Audit entries record event IDs, authority IDs, affected item IDs, decision, actor, and correlation ID. The authority-event audit records `flag_for_review`; it does not record a legal conclusion. Event-processing errors persist only their exception class, not an exception message that could contain a secret.
- The audit journal is hash chained and audit packs verify hashes. It is not an externally anchored, independently signed immutable ledger unless an operator adds such an anchor. Optional verification attestations exist, but the proof does not configure an attestation key.
- SQLite is the local default. Server deployments use per-tenant directories or a PostgreSQL schema per tenant. This proof demonstrates scoped MCP calls inside one local scenario; it is not a formal multi-process tenancy penetration test.
- Source documents and candidate claims can use configured envelope encryption. Knowledge-event payloads and the local audit journal are not independently field-encrypted by this scenario. Operators must provide filesystem, database, backup, and key-management controls appropriate to their jurisdiction.
- Models are optional. The proof does not invoke one. When models are configured, context flows through the boundary; zero-egress deployments use local endpoints, and remote use requires explicit policy and is still a boundary crossing. Pseudonymization, quarantine, monitoring, and local/server deployment choices are operational controls described in the architecture and trust-boundary documents, not legal guarantees.

## Acceptance and verification

The milestone is accepted locally when all of the following are true:

1. One authority event makes exactly two direct and one transitive dependent stale, leaving the unrelated second-scope item live.
2. Default recall excludes stale items; review-mode recall returns each item with a reason that includes the durable `change_id`.
3. A restricted MCP principal can retrieve only its permitted scope and is denied a second-scope impact request.
4. Review tasks require assignment and reviewer identity. Reaffirmation restores live recall; supersession preserves predecessor history and exposes the live successor.
5. An `as_of` query before the authority event returns predecessors only within the requested scope.
6. Audit-pack verification succeeds. Restarted duplicate event replay adds no stale event, review task, or impact audit entry.
7. A simulated interruption after propagation and before task creation is visible as an incomplete workflow event and retries without duplication (`tests/test_currency_loop_proof.py`).
8. The cycle probe terminates with unique impacts; a bounded failed authority poll is retained/retried/dead-lettered by `tests/test_authority_polling.py`.

Relevant commands:

```bash
uv run pytest -q tests/test_currency_loop_proof.py tests/test_currency_loop_demo.py
uv run python examples/scenarios/currency-loop-proof/run.py --workspace /tmp/solomon-currency-loop-proof
```

The full test suite and optional real PostgreSQL integration remain the release verification, not a substitute for pilot evidence.

## Evaluation result and limits

The committed snapshot records direct impact = 2, transitive impact = 1, unrelated impact = 0, permitted scoped impacts = 3, cross-scope denial = true, duplicate replay = true, cycle bounded = true, three explainable stale reasons, three review tasks, one impact audit event, and audit-pack verification = true. The raw result carries the actual local latency and checks it against 2,000 ms.

This result uses tiny synthetic data, a local process, deterministic embeddings, a supplied authority event, and a preconfigured policy. It does not establish recall quality on real firm data, authority-feed completeness, horizontal-scale capacity, latency under concurrent load, legal correctness, client confidentiality compliance, or user adoption. Pilot validation is deliberately separate in [`docs/pilot-validation-plan.md`](../pilot-validation-plan.md).

## Release gate and next milestone

Before any public release, run `scripts/release_quality_gates.py`, package checks, container/Helm configuration checks, optional real PostgreSQL integration, and the headless proof. External publication prerequisites (package ownership, trusted publishers, marketplace/listing choices, hosted CI billing, and native macOS/Nix evidence) are release-gate work rather than assertions made by this milestone.

Recommended next milestone: **run a bounded internal legal-knowledge pilot using the Currency Loop Proof protocol and publish only observed review-time, avoided-reuse, and operator-feedback evidence.**
