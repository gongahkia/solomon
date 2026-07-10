# Curator console user guide

Persona: Maya Tan, a fictional KM lawyer at a Singapore firm, reviews internal house views after an authority update.

## Start the console

```bash
uv run solomon console serve --host 127.0.0.1 --port 8150
```

Open `http://127.0.0.1:8150/console`.

For dev-mode bearer auth, set `SOLOMON_CONSOLE_BEARER_TOKEN` and send `Authorization: Bearer <token>`. SSO, RBAC, and sessions are outside this portfolio console scope.

## 1. Clear verification items

Maya starts in [Verification Desk](verification-desk.md).

She scans rows flagged stale, contested, or needing review. For each row, she checks:

- currency state and stale reason.
- source reference and credence tier.
- knowledge excerpt.
- upstream dependencies and downstream dependents.

If the old position is still acceptable, she chooses `reaffirm`, enters her partner or reviewer id, adds an evidence reference, and submits. If the position has moved, she chooses `supersede` with the successor item id or `retire` if it should no longer be recalled as live knowledge. She uses `pin` only when a firm-authoritative floor is justified.

## 2. Confirm dependency suggestions

Next, Maya opens [Dependency Review](dependency-review.md).

The left queue shows suggested edges from deterministic reference extraction. She filters by authority id when reviewing one update, inspects the graph panel, and enters her reviewer id before accepting or rejecting each suggestion.

Accepting a suggestion creates a confirmed dependency edge and records the decision in the audit journal. Rejecting keeps the review history without changing the dependency graph.

## 3. Run the currency report

Maya opens [Currency Report](currency-report.md), chooses the quarter and matter scope, and exports the partner-facing list of positions that went stale, contradictory, superseded, or retired. Each row shows the moved authority or dependency, current verification status, and dependent item count.

## 4. Export an audit pack

Finally, Maya opens [Audit Pack](audit-pack.md).

She searches by item id or query, selects the relevant item, checks provenance, verification, dependency, boundary, and hash-chain evidence, then exports:

- JSON for machine-readable `manifest.json`, `journal.jsonl`, and selected-item evidence.
- PDF for a compact human-readable summary.

The exported pack is evidence for why Solomon treated the item as live, stale, superseded, retired, or review-required at that point in time.

## Daily close

Maya finishes when the verification queue is empty, material dependency suggestions are accepted or rejected, the period currency report is exported, and audit packs are exported for any contested or client-sensitive decisions.
