<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production Operations Troubleshooting

This guide applies only to Solomon's recommended single-host PostgreSQL/SQLite/JSONL Compose profile. It preserves
evidence and availability boundaries; it does not authorize manual edits to PostgreSQL tables, SQLite files, audit
JSONL, restore plans, or backup manifests. Never include passwords, backup passphrases, raw source evidence, or
unredacted database URLs in tickets or pasted command output.

Start every investigation by saving redacted, stable JSON from the affected deployment:

```bash
solomon deployment preflight --require-initialized --format json
solomon deployment compatibility
solomon deployment maintenance --format json
solomon deployment verify --matter-id <exact-matter> --client-id <exact-client> --format json
solomon consistency operations --matter-id <exact-matter> --client-id <exact-client> --format json
```

`deployment verify` reports `failed`, `degraded`, or `ready`; a degraded result can deliberately expose recoverable
queued work. Keep the emitted reports, the deployment identifier, the maintenance operation identifier if present,
and the relevant audit-pack verification result with the incident record.

## Failed migration or startup after migration

Do not start an older binary against a database that the target version has migrated. An unknown schema version is an
intentional compatibility refusal, not a reason to force startup or delete a row from `schema_migrations`.

1. Stop the failed target API, console, and worker so no additional work is claimed.
2. Run `solomon deployment upgrade-preflight --format json` using the intended target version. Preserve its redacted
   report and the migration log.
3. Inspect the migration status with the target version only. Re-running `solomon migrate` is allowed when the
   framework reports a recoverable, compatible forward migration; PostgreSQL advisory locking and local exclusion
   prevent concurrent migration attempts.
4. If the target cannot start after a completed migration, choose forward repair after investigation or restore the
   verified pre-upgrade checkpoint into fresh isolated targets. Do not invent a database downgrade.
5. Before accepting traffic, run preflight, a scoped deployment verification, the worker, the consistency inspector,
   and audit-pack verification.

Application rollback is permitted only when the earlier application declares the recorded schema readable. This
release proves the opposite case for operation-store schema version 2: the old binary refuses it. Configuration
rollback is separate from application rollback; restore the previous configuration from the approved secret/config
source without placing it in a Solomon application-data backup.

## Incomplete or interrupted backup

A usable backup consists of both the encrypted archive and its adjacent `.manifest.json` sidecar. Treat an archive
without a verified matching sidecar, an `INCOMPLETE.json` staging marker, a failed `backup-inspect`, or a missing
`deployment_backup_completed` audit entry as non-restorable.

1. Do not move, rename, or restore the incomplete artifact.
2. Inspect maintenance state: `solomon deployment maintenance --format json`. Compare the persisted owner and
   operation ID with the still-running backup process before taking any action.
3. If the owner is confirmed absent and PostgreSQL, local data, and the audit journal are healthy, release only that
   exact persisted operation: `solomon deployment release-maintenance --operation-id <operation-id>`.
4. Keep the incomplete staging directory and the live audit history as incident evidence. Create a new archive at a
   different new destination; do not retry by overwriting or appending to the old path.
5. Run `solomon deployment backup-inspect <new-archive>` before relying on the new checkpoint.

The maintenance gate is supposed to reject mutations and new worker claims during capture. If it is still active
after a hard termination, operator confirmation is required because ordinary cleanup could not establish whether the
former owner reached a safe checkpoint.

## Failed restore or a stale restore plan

Restore is intentionally one-way and target-specific. It never deletes an existing local root or a populated target
database to make a retry easier.

| Symptom | Safe response |
| --- | --- |
| archive, manifest, or passphrase verification fails | Stop. Preserve the pair, record only its SHA-256 identity, and acquire a verified backup pair. Do not attempt extraction by another tool. |
| plan generation refuses the target | Use an absent local target and an empty PostgreSQL database with the recorded database name and role. Do not empty an existing target for this purpose. |
| apply refuses a stale plan | Generate a new plan after validating the archive and target; apply only its unchanged JSON output. |
| PostgreSQL restore, SQLite integrity, or audit verification fails | Keep the target isolated and unstarted. Preserve logs and staged/activated evidence, then restore a verified checkpoint into a fresh empty target. |
| interruption after local activation | Do not retry against that target. The staged journal may record `deployment_restore_started` without completion; preserve it and choose a fresh target or verified checkpoint. |

After a successful restore, run the post-restore sequence in the [backup, restore, and upgrade runbook](./production-backup-restore.md#restore-planning-and-apply). A restore does not authorize a repair that would create an edge from a pending, rejected, deferred, withdrawn, expired, or otherwise unconfirmed assertion.

## Incompatible rollback

Never bypass an incompatible application rollback by changing schema metadata, bypassing preflight, or restoring only
one persistence component. The valid recovery choices are:

- start a compatible prior application only after its compatibility report admits the recorded schema;
- restore the verified pre-upgrade checkpoint into fresh local and PostgreSQL targets; or
- repair forward with the target version after investigation.

The bounded upgrade rehearsal proves the second choice and proves refusal of the incompatible old binary. It does not
prove an automatic or safe schema downgrade. See the [upgrade and rollback policy](./production-backup-restore.md#upgrade-and-rollback) and the [production operations ADR](../adr/0011-production-operations-profile.md) for the compatibility boundary.

## Escalation record

For any operator-required condition, retain the redacted command reports, deployment and maintenance IDs, backup
archive/manifest digests, migration version list, audit-pack verification, scoped consistency findings, and exact
target paths. Do not retain active credentials, passphrases, raw evidence, or private keys in the record. Use the
[crash consistency operations guide](./crash-consistency.md) for safe journal repair and retry decisions.
