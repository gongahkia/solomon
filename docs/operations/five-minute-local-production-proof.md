<!-- SPDX-License-Identifier: Apache-2.0 -->

# Five-Minute Local Production Proof

This is a concise, disposable proof of the recommended mixed PostgreSQL/SQLite/JSONL operational profile. It is not
a deployment recipe for an existing service and it is not a production RTO claim. The most recent recorded run took
198.536 seconds of host-monotonic time for its four-item, two-scope fixture; cold image downloads, an unfamiliar
Docker host, or constrained hardware can exceed five minutes.

## Prerequisites

Run from a clean checkout with Docker Engine available. The script creates process-ID-scoped containers, networks,
images, and temporary state only; it does not use configured Solomon directories, named volumes, external databases,
or operator credentials. Do not point it at a report path that already exists.

## Run the proof

```bash
report_dir="$(mktemp -d)"
SOLOMON_OPERATIONS_REPORT_PATH="$report_dir/operations-report.json" \
  scripts/production_operations_rehearsal.sh
```

The script fails loudly on an invariant violation and emits one stable JSON report. A successful report has
`"schema_id": "solomon.production_operations_rehearsal.v3"` and `"result": "passed"`.

## What this proves

The rehearsal uses real PostgreSQL 16 + pgvector and real SQLite files. It performs deployment initialization and
preflight, creates scoped governed assertions and source lineage, demonstrates graph/currency effects, retains a
queued recoverable operation, creates and inspects an encrypted coordinated checkpoint, restores into an isolated
empty PostgreSQL target and absent local root, compares canonical semantic inventories, verifies an audit pack,
resumes the safe queued operation, and makes a valid post-restore governed write.

Its JSON includes component counts, semantic-inventory equality, verification state before and after recovery, audit
status, recovery-point wording, and host-monotonic timings for initialization, backup, inspection, restore planning,
restore apply, and post-restore validation. Keep the report as local engineering evidence only; it is not a service
level objective or an externally validated recovery measurement.

## What it does not prove

This compact proof does not replace the separate real N-to-N+1 upgrade rehearsal:

```bash
scripts/production_upgrade_rehearsal.sh
```

It also does not validate a Kubernetes runtime, a managed PostgreSQL service, geographic recovery, cross-store
point-in-time atomicity, or an external RPO/RTO. See the full [backup, restore, and upgrade runbook](./production-backup-restore.md),
[production rehearsal record](../evaluations/production-operations-rehearsal.md), and
[deployment support matrix](../deployment-support-matrix.md) before operating a non-disposable deployment.
