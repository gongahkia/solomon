<!-- SPDX-License-Identifier: Apache-2.0 -->

# Deployment Support Matrix

This matrix classifies repository artifacts by exercised evidence, not by whether an artifact merely renders or
builds. The canonical production rehearsal is the single-host production Compose profile described in the locked
[operations contract](./roadmap/production-operations-rehearsal.md).

| Mode or component | Classification | Evidence and constraint |
| --- | --- | --- |
| `docker-compose.production.yml` | recommended production | Canonical single-host mixed PostgreSQL/SQLite/JSONL profile; requires all three durable volumes, secret files, loopback/TLS-aware binding, one worker, preflight, bootstrap, and coordinated full-backup rehearsal. |
| PostgreSQL 16 + pgvector | required by recommended production | Holds knowledge, graph, retrieval, and operation journal. The supported image/version is pinned by production Compose. |
| `solomon-data` and `solomon-journal` local volumes | required by recommended production | Hold authoritative source/workflow/authority SQLite state and audit JSONL; must be included in coordinated backup/restore. |
| SQLite-only profile | supported but constrained | Offline/local single-writer profile; no cluster or network-filesystem claim. |
| mixed SQLite/PostgreSQL profile | recommended production | Recoverable through durable-operation reconciliation and an encrypted full checkpoint/guarded restore; not cross-store atomic or point-in-time atomic. |
| server Compose development file | development/local only | Mounts the checkout and installs dependencies at startup; it is not the production rehearsal. |
| Helm chart | experimental | Static chart validation exists. Runtime Kubernetes proof, disruption behavior, backup/restore, upgrade, and persistent-volume recovery are unverified without a local cluster. |
| Python package/service | supported operator artifact | Provides API/CLI process code but does not independently define a production topology, backup destination, or worker supervision. |
| PyInstaller binary | local/operator only | Binary smoke is exercised; it is not a server deployment/backup topology. |
| audit JSONL | required local persistence | Hash chained and file-locked on a shared POSIX filesystem. It is not an object-store or multi-region audit system. |
| filesystem/object storage | filesystem only | Source documents live in the local state volume. No object-store backend is implemented or supported. |
| CLI | supported | Operational mutation is CLI-only with stable JSON where documented. |
| REST administration | constrained | Existing authenticated API conventions remain available; this milestone does not require a new destructive restore endpoint. |
| maintained SDKs | supported read/API clients | Updated only if a supported REST contract changes. |
| MCP | supported read-only | No backup, restore, migration, or repair mutation is exposed. |
| operation worker | required in recommended production | Resumes journal work after restart; single worker is required for source sync until a distributed source lease exists. |

The PostgreSQL database can be operated as a managed or separately replicated service, but this repository proves only
the single-node disposable Compose topology. API, console, worker, migrations, and the local state volume must not be
horizontally scaled independently because source/workflow SQLite and audit JSONL are shared ancillary state. See the
[production operations guide](./operations/production-backup-restore.md) for the tested checkpoint, restore, and
forward-only upgrade procedure.
