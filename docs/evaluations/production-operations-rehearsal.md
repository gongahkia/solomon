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
| Focused implementation tests | `uv run pytest -q tests/test_backup.py tests/test_backup_subprocess_interruption.py tests/test_cli.py tests/test_deployment.py tests/test_semantic_inventory.py tests/test_governed_dependency_assertion_demo.py` | 49 passed after governed restore, readiness verification, archive-bound, and abrupt-interruption work. |
| Full suite and coverage | `SOLOMON_TEST_POSTGRES_DSN=… uv run pytest --cov=src/solomon` | 540 collected with an isolated live pgvector PostgreSQL; coverage report passed at 90%. A first no-PostgreSQL invocation reached only 88%, so it is not used as release evidence. |
| Static checks | `uv run ruff check …` and `uv run mypy …` over changed deployment, backup, CLI, migration, and test files | Passed at each implementation phase. |
| Compose model | `TMPDIR=/home/gongahkia /bin/sh scripts/check_production_compose.sh` | Passed. |
| Production Compose smoke | `TMPDIR=/home/gongahkia/solomon-verification.qF5pz4 timeout 600 scripts/production_compose_smoke.sh` | Passed: production image build, migration, bootstrap, API, console, and worker smoke. |
| Full checkpoint/restore | `TMPDIR=/home/gongahkia/solomon-verification.qF5pz4 SOLOMON_OPERATIONS_REPORT_PATH=… timeout 600 scripts/production_operations_rehearsal.sh` | Passed with real isolated pgvector PostgreSQL; retained report schema `solomon.production_operations_rehearsal.v2`. |
| N-to-N+1 upgrade | `TMPDIR=/home/gongahkia/solomon-verification.qF5pz4 SOLOMON_UPGRADE_REPORT_PATH=… timeout 900 scripts/production_upgrade_rehearsal.sh` | Passed with real isolated pgvector PostgreSQL; retained report schema `solomon.production_upgrade_rehearsal.v2`. |
| Release surfaces | TypeScript `npm ci && npm run typecheck && npm test`; `scripts/check_helm_chart.sh`; PyInstaller and `scripts/smoke_local_binary.py`; `scripts/release_quality_gates.py` | Passed. Helm result is static validation only. |

The checkpoint/restore scenario starts from a migrated, initialized source profile and exercises two isolated scopes.
It creates human and trusted-upstream assertions in pending, confirmed, rejected, deferred, and withdrawn states;
preserves source version lineage and a reverification request; proves the confirmed edge's currency effect; verifies
scope denial, confirmation idempotency, audit-pack integrity, source and restored readiness, and zero scoped
consistency findings. It creates and inspects an encrypted full backup, refuses application tables before restore,
restores an empty isolated PostgreSQL target and absent local root, compares 12 canonical content-redacting semantic
component hashes (including source documents, candidates, local SQLite state, graph, operations, and audit
correlation), verifies the retained audit pack, and completes a new governed post-restore graph write with matching
assertion provenance. The checkpoint also contains a queued duplicate confirmation for an existing validly confirmed
assertion: source and restored readiness report it as degraded, the restarted worker completes it without a duplicate
edge or currency effect, the consistency report remains empty, and readiness returns to ready. This demonstrates
component recovery and continued operation; it does not prove distributed atomic restore.

The upgrade scenario builds committed `2d74983b` for N and current HEAD for N+1. The actual N binary creates the
same two-scope governed fixture: source/version lineage, confirmed/rejected/deferred/withdrawn assertions, graph and
currency effects, audit pack, and lifecycle safeguards. The current release creates and verifies a pre-upgrade
checkpoint before migration, restores it into a second empty pgvector target, and proves the N binary still reads the
four-item isolated recovery state. N+1 then applies operation-store migration 2, performs a new governed
confirmation, and produces a verified post-upgrade checkpoint. PostgreSQL reports versions `[1, 2]`. N refuses the
unknown source-schema version; N+1 health verifies its audit chain and reports the five-item inventory. This is a
safe rollback refusal and isolated restore rehearsal, not an in-place database downgrade.

## Failure and guard coverage

Focused tests cover tampered encrypted archives, manifest/archive digest drift, wrong passphrase, existing target
refusal, unsafe paths and links, active-tree backup-destination refusal, member-count/per-member/total archive
bounds, invalid audit journal, incomplete backup staging on injected PostgreSQL dump failure, a real `SIGKILL` during
the PostgreSQL-capture boundary, stale plan refusal, database identity mismatch, password exclusion from PostgreSQL
client arguments, maintenance write/worker blocking, concurrent bootstrap, read-only CLI load/restore planning,
read-only scoped deployment verification, migration rollback on a failed fresh SQLite batch, and operation-store
N-to-N+1 migration.

The existing crash-consistency scenario and proof record remain the evidence for operation interruption, duplicate
delivery, concurrent worker claims, safe repair, cross-scope refusal, and audit-pack verification. This operations
rehearsal does not replace those tests or introduce a new extraction/parser baseline.

## Limits

Not run here: a live Kubernetes/Helm deployment, managed PostgreSQL backup/restore, external backup replication,
incremental backup, performance/RPO/RTO measurement, multi-host failure, a physical host power-loss simulation during
backup/restore, or the complete release-quality suite. Helm remains static-only and experimental. These omissions
mean no broader production availability or disaster-recovery claim is made.
