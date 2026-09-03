<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production Backup Security And Excluded Secrets

This guide covers the recommended single-host PostgreSQL/SQLite/JSONL profile only. It describes the protections
tested by Solomon's backup and restore commands and the security responsibilities that remain with the operator.
It is not a security certification, a multi-region recovery design, or a replacement for an organisation's key,
access, retention, and incident-response policies.

## What a server backup contains

`solomon deployment backup` creates a new, encrypted full checkpoint and a matching `.manifest.json` sidecar. The
archive contains a custom PostgreSQL logical dump, SQLite snapshots made with SQLite's backup API, local durable
state, the bounded audit journal, and versioned backup metadata. The metadata identifies the deployment, included
scopes, schema versions, operation checkpoint, audit bound, file sizes, SHA-256 digests, quiescence method, excluded
categories, and tool versions.

The archive encryption is provided by the supplied backup passphrase. SHA-256 digests establish artifact identity
and tamper detection; they are not encryption. Store the archive, sidecar, and passphrase separately. An archive is
not usable until `solomon deployment backup-inspect` validates the encrypted archive, sidecar, manifest, and every
included member.

## Secrets deliberately excluded

Application-data backups do **not** include:

- PostgreSQL passwords, database URLs containing credentials, or client environment variables;
- `SOLOMON_BACKUP_PASSPHRASE` and any approved secret-store material;
- content-encryption keys, KMS references or credentials, JWT signing keys, OIDC client secrets, API keys, or
  private keys;
- Compose `.env` files, secret files, private deployment configuration, Docker credentials, or host configuration;
- operator shell history, logs, tickets, raw source evidence copied for incident analysis, or independently managed
  external-service credentials.

The operator must restore excluded configuration and secret references from the approved configuration and secret
systems before starting a restored deployment. Do not add secrets to a backup directory to make recovery easier, and
do not paste a connection URL or passphrase into a restore plan, command transcript, or support record.

## Artifact and destination controls

Use a new destination outside active `solomon-data` and `solomon-journal` roots. Solomon rejects a destination inside
those roots to avoid recursive capture and keeps staging directories private. The operator should also restrict
directory access, separate backup-operator and service identities where practical, retain artifacts under the
organisation's backup policy, and copy the verified archive/sidecar pair using an approved encrypted transport.

Do not rely on a successful file copy as backup verification. Re-run `backup-inspect` after the destination copy,
using the passphrase from the approved secret store. A missing sidecar, mismatched digest, incomplete marker, failed
inspection, or unexpected file means the pair is not restorable.

## Restore admission controls

Restore planning checks the encrypted archive before it produces a stable fingerprint. Apply rechecks the plan and
refuses incomplete, tampered, truncated, unsupported, path-traversing, duplicate, linked, oversized, or unexpected
archive members. Archive admission limits member count, individual member size, and total declared extracted size
before materializing data.

The restore target is bound to the plan. It must be an absent local root and an empty PostgreSQL target with the
recorded database identity. Solomon will not empty a target, follow a symlink, or accept an edited/stale plan. A
restored deployment still enforces tenant scope, review state, and journal reconciliation; recovery is not an
authorization bypass.

## Operator response to a suspected exposure

1. Stop distributing the archive and sidecar; preserve them as evidence without modifying their contents.
2. Treat the backup passphrase and any deployment secret that may have been exposed outside its approved system as
   compromised; rotate it through the relevant secret-management procedure.
3. Record only archive identities, deployment IDs, target paths, and redacted command reports in the incident record.
4. Verify an unaffected backup pair before recovery. Restore only to fresh isolated targets, then run post-restore
   verification before returning data to service.

See the [backup, restore, and upgrade runbook](./production-backup-restore.md) for the operational sequence and the
[troubleshooting guide](./production-troubleshooting.md) for incomplete backup and restore-failure handling.
