<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production Backup, Restore, And Upgrade Operations

This guide applies only to the recommended single-host mixed PostgreSQL/SQLite/JSONL profile. It is a coordinated
checkpoint and recovery procedure, not a distributed transaction or a point-in-time recovery product.

## Before any operation

Keep the PostgreSQL volume/database, `solomon-data`, and `solomon-journal` together. Losing any one of them means
the deployment cannot make the normal reconstructibility claim. Keep the backup passphrase outside the deployment;
Solomon reads it only from `SOLOMON_BACKUP_PASSPHRASE`. Do not put it in a shell history, Compose environment file,
ticket, or plan file.

Check the current layout without creating data or applying a migration:

```bash
docker compose -f docker-compose.production.yml --profile production exec api \
  solomon deployment preflight --require-initialized --format json
docker compose -f docker-compose.production.yml --profile production exec api \
  solomon deployment compatibility
docker compose -f docker-compose.production.yml --profile production exec api \
  solomon deployment verify --matter-id <exact-matter> --client-id <exact-client> --format json
```

`preflight` is read-only. A blocked audit chain, inaccessible local directory, profile mismatch, unreachable
PostgreSQL, or unavailable pgvector is a stop condition. `compatibility` is an application/layout report, not a
database-downgrade promise. `deployment verify` adds runtime audit verification, durable-operation visibility, one
exact scoped read, and the scoped consistency inspector. Its `liveness`, `readiness`, and `state` fields distinguish
a failed dependency from a deployable but operator-visible degraded state; it never writes an application record.

## Full backup

Run the command from a controlled one-shot container or the API container while the other long-running Solomon
processes are stopped. The command takes the durable maintenance gate, rejects new Solomon mutations and worker
claims, writes a `deployment_backup_started` audit event, and then captures the components below.

```bash
export SOLOMON_BACKUP_PASSPHRASE='obtain-from-approved-secret-store'
docker compose -f docker-compose.production.yml --profile production run --rm --no-deps api \
  solomon deployment backup /backup/solomon-server-YYYYMMDD.enc
docker compose -f docker-compose.production.yml --profile production run --rm --no-deps api \
  solomon deployment backup-inspect /backup/solomon-server-YYYYMMDD.enc
```

The destination must be new and outside the active data and audit trees. The full encrypted archive contains safe
SQLite snapshots, the local JSON/JSONL state,
and a custom-format PostgreSQL logical dump. Its adjacent `.manifest.json` binds encrypted and decrypted SHA-256
digests, deployment identity, maintenance operation ID, and archive metadata. The passphrase and connection password
are not written to arguments, plan JSON, or the manifest. The backup is only complete after both archive and sidecar
are published and `deployment_backup_completed` is appended to the live audit journal. The copied audit snapshot
contains the start event; the live journal then records completion. This intentional ordering is not a missing audit
record in the archive. The encrypted archive record separately names a backup ID, included deployment scopes,
PostgreSQL schema versions and operation high-water mark, SQLite snapshot identities, audit entry count and digest,
quiescence method, excluded runtime-secret categories, and the `pg_dump`/Solomon tool versions. `backup-inspect`
validates the archive before presenting that record.

There is no incremental backup, remote-object-store copy, retention scheduler, external RPO, external RTO, or
managed PostgreSQL physical-backup claim. Copy the archive and sidecar off the host using the organisation's approved
encrypted backup system, then test the copied pair with `backup-inspect`. Archive inspection rejects links, duplicate
paths, more than 10,000 entries, an entry over 1 GiB, or more than 4 GiB of declared extracted data before
materializing files.

An ordinary backup failure leaves an `INCOMPLETE.json` marker in the staging directory and releases maintenance. A
hard process termination can leave the maintenance record behind because ordinary cleanup did not run. Do not delete
it blindly: inspect process ownership, archive/staging state, PostgreSQL, and audit history; then use the exact
persisted operation ID with `deployment release-maintenance` only after confirming no backup owner remains.

## Restore planning and apply

Restore never targets an existing local root. Use an empty PostgreSQL database with the same database name and role
as the archive record; a different isolated host is allowed. The target database must contain no application tables.
The plan command does not create data directories, connect to PostgreSQL, or apply a migration.

```bash
export SOLOMON_BACKUP_PASSPHRASE='obtain-from-approved-secret-store'
export SOLOMON_RESTORE_DATABASE_URL='postgresql://solomon:<approved-secret>@isolated-restore-host:5432/solomon'
docker compose -f docker-compose.production.yml --profile production run --rm --no-deps api \
  solomon deployment restore-plan /backup/solomon-server-YYYYMMDD.enc /restore/solomon-state \
  --output /restore/restore-plan.json
docker compose -f docker-compose.production.yml --profile production run --rm --no-deps api \
  solomon deployment restore --plan /restore/restore-plan.json --apply
```

The plan fingerprint includes archive digest, deployment ID, target root, redacted target database URL, and archive
inventory. Apply recomputes it immediately before mutation. It refuses an edited archive/sidecar, a stale plan, an
existing target root, a non-empty database, a database name/role mismatch, unsafe archive member, missing component,
SQLite integrity failure, or audit-chain failure. It uses `pg_restore --single-transaction` for the PostgreSQL
component and activates locally staged `data` and `journal` only after validation.

The boundary remains important: a host crash after PostgreSQL restore and before local activation is not rolled back
across both stores. Keep the target isolated, do not start Solomon against it, retain the plan and logs, and have an
operator either rerun from a fresh empty target or restore a verified checkpoint. No automatic destructive
compensation is attempted.

After a successful restore, point a fresh deployment at the restored local paths and database. Run preflight,
health, the scoped consistency inspector, the worker, and audit-pack verification before accepting user traffic:

```bash
solomon deployment preflight --require-initialized --format json
solomon deployment verify --matter-id <exact-matter> --client-id <exact-client> --format json
solomon health
solomon consistency operations --format json
solomon worker --once
```

Use the existing scoped [crash-consistency guide](./crash-consistency.md) for an incomplete governed operation. A
backup restore does not authorize a repair to create a pending, rejected, deferred, withdrawn, or expired assertion
edge.

## Upgrade and rollback

Take and inspect a coordinated backup first. Then use only the target image/version to perform a read-only admission
check and forward migration:

```bash
solomon deployment upgrade-preflight --format json
solomon migrate
solomon deployment preflight --require-initialized --format json
solomon worker --once
```

PostgreSQL migrations serialize on an advisory lock. The operation-store 2 migration adds the
`idx_knowledge_operations_status_updated` index; it does not rewrite operation or audit history. Re-running
`migrate` is idempotent. An older binary rejects the unknown version 2 migration, so rollback is not an in-place
database downgrade. Stop the failed target binary and restore the verified pre-upgrade checkpoint into fresh targets,
or make a forward repair after investigation.

The real N-to-N+1 rehearsal is available to an operator with Docker and the repository history:

```bash
TMPDIR=/safe/temp scripts/production_upgrade_rehearsal.sh
```

It uses `2d74983b` as its committed N revision by default, builds isolated images, creates no named volumes, takes
and verifies pre- and post-upgrade checkpoints, restores the pre-upgrade checkpoint into a second empty pgvector
target, proves the N binary can read that isolated recovery target, verifies versions 1 and 2 in the upgraded
PostgreSQL source, proves the old binary refuses N+1, and performs a current-version write afterward.
