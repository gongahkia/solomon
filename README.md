# Solomon

<p align="center">
  <img src="./asset/logo/solomon.png" width="50%">
</p>

<h3 align="center">Self-hosted provenance and change-impact control for high-stakes AI.</h3>

<p align="center">
  <a href="./docs/index.md">Documentation</a> ·
  <a href="./docs/positioning.md">Why Solomon</a> ·
  <a href="./docs/deployment.md">Deployment</a> ·
  <a href="./docs/pilot/owner-operated-protocol.md">Pilot protocol</a>
</p>

<p align="center">
  <a href="https://github.com/gongahkia/solomon/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/gongahkia/solomon/ci.yml?branch=main&style=flat-square"></a>
  <img alt="MCP compatible" src="https://img.shields.io/badge/MCP-compatible-7C3AED?style=flat-square">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square">
  <img alt="Coverage gate 90 percent" src="https://img.shields.io/badge/coverage%20gate-%E2%89%A590%25-brightgreen?style=flat-square">
  <img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square">
</p>

Solomon tells a host application whether internal knowledge is still usable, what it depends on, and what needs human
re-verification. It is built for legal knowledge first, but its core job is general: preserve provenance, make
dependency impact visible, and keep stale material from quietly being reused.

**Flag, do not adjudicate.** Solomon does not decide the law, replace professional judgement, or certify that a
position is correct.

## Contents

- [🚀 Start with Solomon](#-start-with-solomon)
- [🤔 Why Solomon?](#-why-solomon)
- [🔎 How it works](#-how-it-works)
- [👀 Choose an entry point](#-choose-an-entry-point)
- [🧪 See it in action](#-see-it-in-action)
- [🛟 Operate it carefully](#-operate-it-carefully)
- [📚 Learn more](#-learn-more)
- [🧭 Owner-operated pilot](#-owner-operated-pilot)
- [🌟 Contributing](#-contributing)

## 🚀 Start with Solomon

Install the local, offline-default profile:

```bash
uv sync
uv run solomon diagnostics
```

Ingest a position and retrieve only currently usable knowledge:

```bash
uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1
uv run solomon recall "structure X regulation"
```

Solomon also runs as an MCP server for compatible hosts:

```bash
uv run solomon mcp serve --help
```

For SDKs, console setup, and full command reference, start with the [documentation index](./docs/index.md).

## 🤔 Why Solomon?

Retrieval answers “what material might help?” Solomon adds the evidence needed to decide whether that material should
still be reused.

| When you need to… | Solomon helps by… |
| --- | --- |
| understand an internal position | retaining provenance, source versions, credence, and verification history |
| record reliance on an authority or another position | keeping a proposed dependency under human review until it is confirmed |
| respond when an authority changes | propagating `StalePendingReverification` through confirmed dependencies |
| explain a review obligation | exposing `why`, scoped impact, timeline, and audit evidence |
| recover after an interruption | retaining durable operation history and reconciling only defined safe states |

Solomon complements a DMS, search product, research service, drafting tool, or AI host. Those systems can provide
documents or draft work; Solomon provides a deterministic currency gate and the evidence behind it.

## 🔎 How it works

1. **Ingest with provenance.** Knowledge records preserve where material came from and which scope owns it.
2. **Review dependencies.** Deterministic extraction can propose cited reliance, but proposals remain unconfirmed until
   a human curator reviews them. Human or trusted-upstream assertions follow the same governed lifecycle.
3. **Record a change.** When an authority or upstream position changes, Solomon finds affected confirmed edges and
   marks dependent knowledge for re-verification.
4. **Let a human decide.** A reviewer can reaffirm, supersede, retire, or defer work with evidence; Solomon never
   converts a flag into a legal conclusion.
5. **Keep the trail.** Metadata-only, hash-chained audit evidence and audit packs support reconstruction of what
   happened and why.

Read the [architecture](./docs/architecture.md), [concepts](./docs/concepts.md), and
[currency loop proof](./docs/roadmap/currency-loop-proof.md) for the full model.

## 👀 Choose an entry point

| Entry point | Best for | Start here |
| --- | --- | --- |
| Local CLI | an offline-default single-user loop using SQLite | [`solomon` commands](./docs/index.md) |
| MCP and SDKs | a compatible host that needs deterministic current-context, impact, `why`, and audit tools | [MCP installation](./docs/mcp/install.md) · [SDKs](./docs/sdk/index.md) |
| Curator console | reviewing sources, dependencies, verification work, and audit packs | [Console guide](./docs/console/index.md) |
| Server profile | authenticated tenant-aware API, pgvector retrieval, worker recovery, and operations controls | [Deployment profiles](./docs/deployment.md) |

## 🧪 See it in action

Run deterministic, headless proofs with fictional material:

```bash
uv run python examples/scenarios/currency-loop-proof/run.py --workspace /tmp/solomon-currency-loop-proof
uv run python examples/scenarios/evidence-to-dependency-proof/run.py --workspace /tmp/solomon-evidence-to-dependency-proof
uv run python examples/scenarios/governed-dependency-assertion-proof/run.py --workspace /tmp/solomon-governed-assertions
```

Each scenario has a declared scope and limits:

- [Currency Loop Proof](./docs/roadmap/currency-loop-proof.md): impact propagation, review, history, audit-pack, and restart behavior.
- [Evidence-to-Dependency Proof](./docs/roadmap/evidence-to-dependency-proof.md): source spans, suggestions, human decisions, and scope boundaries.
- [Governed Dependency Assertions](./docs/evaluations/governed-dependency-assertion-proof.md): explicit reviewed assertions and provenance-preserving edges.
- [Adversarial Dependency Generalization](./docs/evaluations/adversarial-dependency-generalization.md): a locked synthetic challenge with explicit residual limits.

## 🛟 Operate it carefully

The recommended production profile is a single-host, mixed PostgreSQL/SQLite/JSONL Compose deployment with pgvector,
one worker, shared local durable state, and coordinated full checkpoint/restore. It is **not** a distributed
transaction, cross-store point-in-time recovery, multi-region disaster-recovery system, or universal Kubernetes
claim.

```bash
scripts/check_production_compose.sh
scripts/production_compose_smoke.sh
```

Before operating a non-disposable deployment, read the:

- [production deployment profile](./docs/deployment.md);
- [backup, restore, and upgrade runbook](./docs/operations/production-backup-restore.md);
- [backup security and excluded-secrets guide](./docs/operations/production-backup-security.md);
- [operations troubleshooting guide](./docs/operations/production-troubleshooting.md); and
- [latest redacted rehearsal evidence](./docs/evaluations/evidence/2026-09-04-production-rehearsal/README.md).

## 📚 Learn more

- [Positioning and non-claims](./docs/positioning.md)
- [Architecture](./docs/architecture.md) and [trust boundary](./docs/trust-boundary.md)
- [Deployment support matrix](./docs/deployment-support-matrix.md)
- [Audit packs](./docs/console/audit-pack.md) and [crash-consistency operations](./docs/operations/crash-consistency.md)
- [Known limitations](./docs/known-limitations.md)
- [API contract](./docs/api/openapi.json)
- [Five-minute local production proof](./docs/operations/five-minute-local-production-proof.md)

## 🧭 Owner-operated pilot

The production rehearsal is complete; the next step is a bounded owner-operated pilot using a small,
owner-authorized, non-sensitive corpus. It is a structured self-evaluation, not external validation, legal-accuracy
evidence, production adoption, or reviewer-usability validation.

Use the [pilot protocol](./docs/pilot/owner-operated-protocol.md) and keep raw observations outside Git with the
[private results template](./docs/pilot/owner-operated-results-template.md). The protocol requires expected
dependencies and expected impact to be recorded before a planned source change, and includes a comprehension check
for “flag, not adjudicate.”

## 🌟 Contributing

Contributions should preserve Solomon’s core boundary: reviewed dependency evidence, scoped currency state, and human
decision-making. Read [CONTRIBUTING.md](./CONTRIBUTING.md), then run the relevant checks:

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
uv run pytest
```

For package, binary, Compose, Helm, and release-quality checks, see the
[development and release documentation](./docs/index.md).

## License

Solomon is available under the [Apache License 2.0](./LICENSE).
