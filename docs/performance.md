<!-- SPDX-License-Identifier: Apache-2.0 -->

# Performance And Hardening

Solomon-local uses SQLite WAL mode with a busy timeout so separate readers and the single writer can
coexist without corrupting the event log. Propagation is incremental: authority changes call
`get_dependents()` and walk only reachable dependency edges instead of rescanning every item.

The dependency graph has indexes on source, target, and current target validity for `impact_query`.
`solomon.performance` provides small latency and memory budget helpers used by tests and benchmark scripts.

