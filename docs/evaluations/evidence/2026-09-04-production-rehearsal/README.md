<!-- SPDX-License-Identifier: Apache-2.0 -->

# 2026-09-04 Production Rehearsal Evidence

These are redacted JSON reports from two fresh, disposable Docker Engine rehearsals run from commit
`360ccfd296e2d0ec5109d10f7d5f33ae3d1e14ee`. They are local engineering evidence for the recommended single-host
mixed PostgreSQL/SQLite/JSONL profile, not external validation, a production adoption claim, or an RPO/RTO promise.

| Report | Command | Result | SHA-256 |
| --- | --- | --- | --- |
| [`checkpoint-restore-v3.json`](./checkpoint-restore-v3.json) | `scripts/production_operations_rehearsal.sh` | passed | `5f167aa7de4ee8d8d40bac90bbe9639b099468c7408e058d127a671a33e20cf3` |
| [`upgrade-n-to-n-plus-one-v2.json`](./upgrade-n-to-n-plus-one-v2.json) | `scripts/production_upgrade_rehearsal.sh` | passed | `82de975847237ea3bc226e7700455dd3ad964609f02a5e51f2b1ee6613f73999` |

The checkpoint/restore report records real PostgreSQL 16 + pgvector and SQLite recovery, semantic-inventory equality,
audit-pack verification, safe queued-operation recovery, and a valid post-restore write. The upgrade report starts
from committed `2d74983`, verifies a pre-upgrade restore with the earlier binary, records operation-store versions
`[1, 2]`, verifies the post-upgrade backup, and records refusal of the incompatible old binary.

Before tracking either report, a recursive string-level redaction check found no passwords, passphrases, secrets,
tokens, private keys, PostgreSQL DSNs, home/tmp/state paths, or raw source evidence. The reports contain fixture
counts, bounded lifecycle labels, boolean proof results, schema identifiers, and local elapsed times only.

The scripts created process-scoped containers, networks, images, and temporary state, then removed their own Docker
resources. They did not use an operator database, configured Solomon directory, named volume, or external service.
