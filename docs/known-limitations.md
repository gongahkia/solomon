<!-- SPDX-License-Identifier: Apache-2.0 -->

# Known Limitations

## Durable suggestion generation

The durable operation profile permits the existing deterministic dependency-suggestion parser only. The optional
on-demand LLM suggestion flag is refused because its response is not an immutable replay input; accepting it would
weaken the crash-recovery proof. This does not change parser extraction semantics or promote any suggestion to an
edge.

- External authority monitoring is not comprehensive; v0.1 supports manual and structured change entry.
- The local retrieval index is deterministic and lightweight; production semantic backends can be swapped in.
- Solomon flags moved dependencies and overdue verification. It does not decide whether a legal position is
  wrong.
- Boundary correctness depends on Solomon's detection and tokenization behavior; the committed fixture suite
  is regression evidence, not complete DLP or legal assurance.
- PostgreSQL production remains a mixed SQLite/PostgreSQL/JSONL profile. Individual database writes and operation
  checkpoints are durable, but source-to-graph and graph-to-audit writes are not a distributed ACID transaction.
  Operations converge through bounded retry and reconciliation; unreconstructible, provenance-invalid, or
  authorization-invalid cases require an operator.
- SQLite is a supported offline, single-writer profile. It is not a cluster-scale shared-filesystem multi-writer
  deployment claim.
- The recommended production Compose profile has a tested encrypted full logical checkpoint and guarded restore, but
  no incremental backup, remote object-store replication, external RPO/RTO, managed-service, multi-host, or
  Kubernetes disaster-recovery claim. PostgreSQL restore and local-volume activation are separate actions; a hard
  crash between them requires an operator to recover into fresh isolated targets.
