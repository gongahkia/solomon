<!-- SPDX-License-Identifier: Apache-2.0 -->

# Deployment Profiles And Persistence

## Recommended server profile

Use PostgreSQL with pgvector for knowledge items, graph records, retrieval index, and the durable operation journal.
Each server tenant receives its own PostgreSQL schema. Persist the PostgreSQL volume **and** the mounted
`solomon-data` and `solomon-journal` volumes: the latter contain source-document SQLite, workflow/authority SQLite,
and the hash-chained audit journal. Run a worker after deployment or restart and include all three persistence areas
in backup, restore, and upgrade rehearsals.

This is Solomon's supported mixed SQLite/PostgreSQL production profile. It is not a distributed-ACID profile. A
source version may commit in `sources.sqlite3` before a PostgreSQL operation record, and an operation phase may
commit before its audit JSONL event. Durable reconciliation, phase checkpoints, idempotent projection, inspection,
and guarded repair address those states without claiming a single transaction.

## SQLite-only local profile

SQLite-only remains supported for offline/local, single-writer use. Knowledge, graph, index, and operation journal
share `solomon.sqlite3`; documents/workflow/authority stores and audit journal remain separate local durable files.
SQLite WAL and the persisted operation lease coordinate local processes on a reliable filesystem. Network-filesystem
cluster operation is outside this profile's claim.

## Upgrade requirements

Application startup applies the operation-journal migration in the selected knowledge backend. Upgrade first on a
backup/restored copy, then run:

```bash
uv run solomon migrate
uv run solomon worker --once
uv run solomon consistency operations --format json
```

Do not remove existing SQLite source, workflow, authority, or journal files when switching the knowledge backend.
They remain authoritative state in the mixed deployment. The journal migration preserves existing installations and
does not rewrite historical evidence or parser baselines.

## Compatibility

Existing synchronous API and CLI requests still drain their newly scheduled operation when possible. If interruption
prevents completion, the request can report durable queued work rather than pretending it was atomic. Repeating the
caller idempotency key or restarting the worker resumes the same semantic effect. Existing MCP tools remain read-only.
