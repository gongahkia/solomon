# Curator console user guide

Persona: Maya Tan, a fictional KM lawyer at a Singapore firm, reviews internal house views after an authority update.

## Start the console

```bash
uv run solomon console serve --host 127.0.0.1 --port 8150
```

Open `http://127.0.0.1:8150/console`.

Local mode without configured credentials uses a development-only admin identity. To require a local bearer token, set
`SOLOMON_CONSOLE_BEARER_TOKEN` and send `Authorization: Bearer <token>`; the token's role is
`SOLOMON_CONSOLE_ROLE`, which defaults to `curator`. Server mode requires a bearer token or validated OIDC identity.

| Role | Workflows |
| --- | --- |
| `admin` | all workflows |
| `curator` | claims, sources, dependencies, currency report, audit pack |
| `reviewer` or `lawyer` | verification, reviews, currency report, audit pack |

OIDC role claims use the configured Solomon role mapping. Browser-facing deployments should terminate user identity at
an identity-aware proxy or provide OIDC bearer tokens; the console does not maintain browser sessions.

The complete walkthrough below uses an `admin` identity. Teams with separated duties should follow only the workflows
permitted by their assigned role.

## 1. Clear verification items

Maya starts in [Verification Desk](verification-desk.md).

This screen requires an `admin`, `reviewer`, or `lawyer` role.

She scans rows flagged stale, contested, or needing review. For each row, she checks:

- currency state and stale reason.
- source reference and credence tier.
- knowledge excerpt.
- upstream dependencies and downstream dependents.

If the old position is still acceptable, she chooses `reaffirm`, enters her partner or reviewer id, adds an evidence reference, and submits. If the position has moved, she chooses `supersede` with the successor item id or `retire` if it should no longer be recalled as live knowledge. She uses `pin` only when a firm-authoritative floor is justified.

## 2. Work authority-change review tasks

Maya opens Reviews when an authority change has created a review task. She assigns an open task, starts it when work
begins, and resolves it only after recording the evidence basis and source reference. Urgent tasks are due in one day,
high-priority tasks in three, and normal tasks in seven.

## 3. Confirm dependency suggestions

Next, Maya opens [Dependency Review](dependency-review.md).

The left queue shows suggested edges from deterministic reference extraction. She filters by authority id when reviewing one update, inspects the graph panel, and enters her reviewer id before accepting or rejecting each suggestion.

Accepting a suggestion creates a confirmed dependency edge and records the decision in the audit journal. Rejecting keeps
the review history without changing the dependency graph. This screen requires an `admin` or `curator` role.

## 4. Triage candidate claims and source operations

Maya opens Claims to promote, reject, or defer source-extracted candidate text. A candidate remains source evidence
until a curator records a decision. In Sources, she checks source health and checkpoints, starts a filesystem sync, and
retries a rejected extraction after correcting the source document. Both screens require an `admin` or `curator` role.

## 5. Run the currency report

Maya opens [Currency Report](currency-report.md), chooses the quarter and matter scope, and exports the partner-facing list of positions that went stale, contradictory, superseded, or retired. Each row shows the moved authority or dependency, current verification status, and dependent item count.

## 6. Export an audit pack

Finally, Maya opens [Audit Pack](audit-pack.md).

She searches by item id or query, selects the relevant item, checks provenance, verification, dependency, boundary, and hash-chain evidence, then exports:

- JSON for machine-readable `manifest.json`, `journal.jsonl`, and selected-item evidence.
- PDF for a compact human-readable summary.

The exported pack is evidence for why Solomon treated the item as live, stale, superseded, retired, or review-required at that point in time.

## Daily close

Maya finishes when the verification queue is empty, material dependency suggestions are accepted or rejected, the period currency report is exported, and audit packs are exported for any contested or client-sensitive decisions.
