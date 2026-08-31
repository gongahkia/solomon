<!-- SPDX-License-Identifier: Apache-2.0 -->

# Production Operations Rehearsal Record

## Scope and environment

This record covers the recommended single-host mixed PostgreSQL/SQLite/JSONL profile only. It was run from the
repository after the crash-consistency proof commit `2d74983b`. The harnesses created process-ID-scoped Docker
networks, PostgreSQL 16 + pgvector containers, images, and `mktemp` state only; their traps removed those exact
resources. No named Compose volume, configured Solomon directory, real credential, or external service was used.

The Docker image includes PostgreSQL 16 `pg_dump` and `pg_restore` clients. The image build was checked by invoking
both client `--version` commands and `solomon deployment --help` inside the image. Host PostgreSQL tools are not a
prerequisite for this rehearsal.

## Commands and outcomes

| Check | Command | Observed result |
| --- | --- | --- |
| Baseline focused tests | `uv run pytest -q tests/test_backup.py tests/test_migrations.py tests/test_helm_chart.py tests/test_production_compose.py` | 17 passed before implementation. |
| Focused implementation tests | `uv run pytest -q tests/test_backup.py tests/test_cli.py tests/test_deployment.py tests/test_migrations.py tests/test_production_compose.py` | Passed after backup/restore, read-only planning, and upgrade work. |
| Full suite and coverage | `SOLOMON_TEST_POSTGRES_DSN=… uv run pytest --cov=src/solomon` | 540 collected with an isolated live pgvector PostgreSQL; coverage report passed at 90%. A first no-PostgreSQL invocation reached only 88%, so it is not used as release evidence. |
| Static checks | `uv run ruff check …` and `uv run mypy …` over changed deployment, backup, CLI, migration, and test files | Passed at each implementation phase. |
| Compose model | `TMPDIR=/home/gongahkia /bin/sh scripts/check_production_compose.sh` | Passed. |
| Production Compose smoke | `TMPDIR=/home/gongahkia/solomon-verification.qF5pz4 timeout 600 scripts/production_compose_smoke.sh` | Passed: production image build, migration, bootstrap, API, console, and worker smoke. |
| Full checkpoint/restore | `TMPDIR=/home/gongahkia/solomon-verification.qF5pz4 timeout 600 scripts/production_operations_rehearsal.sh` | Passed with real isolated pgvector PostgreSQL. |
| N-to-N+1 upgrade | `TMPDIR=/home/gongahkia/solomon-verification.qF5pz4 timeout 900 scripts/production_upgrade_rehearsal.sh` | Passed with real isolated pgvector PostgreSQL. |
| Release surfaces | TypeScript `npm ci && npm run typecheck && npm test`; `scripts/check_helm_chart.sh`; PyInstaller and `scripts/smoke_local_binary.py`; `scripts/release_quality_gates.py` | Passed. Helm result is static validation only. |

The checkpoint/restore scenario starts from a migrated, initialized source profile, writes one governed knowledge
record, creates and inspects the encrypted full backup, refuses application tables before restore, restores an empty
isolated PostgreSQL target and absent local root, verifies restored health/audit inventory, and completes a
post-restore write. This demonstrates component recovery and continued operation; it does not prove distributed
atomic restore.

The upgrade scenario builds committed `2d74983b` for N and current HEAD for N+1. N creates the PostgreSQL store and
writes one record. N+1 applies operation-store migration 2, initializes the current deployment marker, passes the
read-only upgrade preflight, and writes a second record. PostgreSQL reports versions `[1, 2]`. N then refuses the
unknown schema version; N+1 health verifies its audit chain and reports the two-record inventory. This is a safe
rollback refusal, not an in-place rollback test.

## Failure and guard coverage

Focused tests cover tampered encrypted archives, manifest/archive digest drift, wrong passphrase, existing target
refusal, unsafe paths and links, invalid audit journal, incomplete backup staging on injected PostgreSQL dump
failure, stale plan refusal, database identity mismatch, password exclusion from PostgreSQL client arguments,
maintenance write/worker blocking, concurrent bootstrap, read-only CLI load/restore planning, migration rollback on
a failed fresh SQLite batch, and operation-store N-to-N+1 migration.

The existing crash-consistency scenario and proof record remain the evidence for operation interruption, duplicate
delivery, concurrent worker claims, safe repair, cross-scope refusal, and audit-pack verification. This operations
rehearsal does not replace those tests or introduce a new extraction/parser baseline.

## Limits

Not run here: a live Kubernetes/Helm deployment, managed PostgreSQL backup/restore, external backup replication,
incremental backup, performance/RPO/RTO measurement, multi-host failure, a physical host power-loss simulation during
backup/restore, or the complete release-quality suite. Helm remains static-only and experimental. These omissions
mean no broader production availability or disaster-recovery claim is made.
