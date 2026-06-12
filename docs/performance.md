<!-- SPDX-License-Identifier: Apache-2.0 -->

# Performance And Hardening

Solomon-local uses SQLite WAL mode with a busy timeout so separate readers and the single writer can
coexist without corrupting the event log. Propagation is incremental: authority changes call
`get_dependents()` and walk only reachable dependency edges instead of rescanning every item.

The dependency graph has indexes on source, target, and current target validity for `impact_query`.
`solomon.performance` provides small latency and memory budget helpers used by tests and benchmark scripts.

## Characterized Local Concurrency

The supported local write envelope is SQLite's WAL model: many readers can coexist with serialized writers,
and writers wait on the configured 5s busy timeout instead of immediately failing on transient lock
contention. CI covers this with a multi-connection write characterization test: 4 independent
`SQLiteKnowledgeStore` connections each append 25 knowledge items to the same database, then the final
materialized state and WAL/busy-timeout pragmas are verified.
