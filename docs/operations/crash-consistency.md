<!-- SPDX-License-Identifier: Apache-2.0 -->

# Crash Consistency Operations Guide

Solomon records a durable operation before it projects a governed confirmation, source reverification, authority
change, deterministic suggestion, or operation-attributed audit event. The worker can resume a safe checkpoint after
an interruption. It does not make separate SQLite, PostgreSQL, and JSONL writes atomic.

## Routine observation

Run the worker after a restart and on its normal cadence:

```bash
uv run solomon worker --once
```

Inspect one exact matter/client selection in stable JSON:

```bash
uv run solomon consistency check --matter-id matter-a --client-id client-a --format json
uv run solomon consistency operations --matter-id matter-a --client-id client-a --format json
```

`consistency operations --format json` without matter/client shows durable operation status for the active tenant,
including tenant-wide authority-change records. The administrative REST equivalents are `GET /consistency/check`,
`GET /consistency/operations`, `POST /consistency/repair/plan`, `POST /consistency/repair/apply`, and
`POST /consistency/operations/{operation_id}/retry`. MCP remains read-only and exposes no repair or retry mutation.

## Interpreting states

- `queued`, `claimed`, and `retrying` are expected temporary states. `claimed` has a persisted 30-second lease.
- `terminal_failed` retained the operation, phase, count, safe failure category, and safe diagnostic after three
  automatic attempts. It remains visible in status and Prometheus operation-state metrics.
- `operator_required` means the worker could not establish safe current scope, provenance, authorization, or source
  lineage. It cannot be retried through the CLI or REST interface.

The metrics surface uses only bounded labels: `solomon_operation_state`,
`solomon_operation_oldest_pending_seconds`, and `solomon_consistency_signal`. Logs and audit entries use operation
correlation identifiers; neither interface should contain raw source text.

## Repair workflow

Planning is dry-run and does not alter graph, document, or currency state:

```bash
uv run solomon consistency repair --matter-id matter-a --client-id client-a > repair-plan.json
uv run solomon consistency repair --plan repair-plan.json --apply
```

The plan has stable report and plan fingerprints. Apply rereads the same scoped items, assertions, edges, operations,
source documents, and relevant audit entries. It refuses a modified, stale, or cross-tenant plan and appends a repair
audit event.

| Finding | Automatic action |
| --- | --- |
| confirmed assertion has no edge and its immutable source lineage still verifies | reproject that existing confirmed assertion only |
| source successor exists without a reverification operation | schedule reverification from preserved document lineage |
| invalid provenance, duplicate edge, missing source version, scope mismatch, audit corruption | none; operator investigation |

Repair never deletes evidence or historical audit entries. It cannot create an edge for a pending, rejected,
deferred, withdrawn, or expired assertion.

## Terminal retry and escalation

After confirming a terminal failure was transient and remains within the same scope, an authorized operator may
requeue it:

```bash
uv run solomon consistency retry OPERATION_ID --by operator-a \
  --matter-id matter-a --client-id client-a
```

Solomon appends `operation_manual_retry_requested` before it records the `manual_retry` operation history entry.
The command queues work only; run the worker to execute it. For an ambiguous finding, retain the JSON report,
operation history, relevant source-document version/hash, and an audit pack. Do not edit the JSONL journal, delete a
graph edge as compensation, or alter source evidence to make a plan apply.
