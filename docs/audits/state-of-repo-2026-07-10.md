# State-of-Repo Audit: 2026-07-10

Issue: https://github.com/gongahkia/shibahama/issues/12

## Commands Run

- `cargo build --all`: passed on 2026-07-10.
- `python3 -m pytest benchmarks`: 14 passed on 2026-07-10.
- `gh issue list --state open --limit 100 --json number,title,body,labels,url,updatedAt`: verified open issue tracker state.
- `rg -n "locomo|longmemeval|Mem0|mem0|Zep|zep|Graphiti|graphiti" benchmarks docs README.md PRD.md`: checked benchmark and comparison coverage.
- `rg -n "struct .*Graph|MemoryGraph|Graph|Entity|Relation|graph" core/src shibahama-cli/src docs/api/README.md`: checked graph storage and API coverage.
- `rg -n "PyO3|pyo3|napi|Node|Python|binding|bindings|stream|snapshot|restore|evaluate_offline_policy|plan_contextual_bandit|assess_stage3" bindings core/src/api.rs docs/api/README.md README.md`: checked binding/API coverage.

## Reviewer-Catch Audit

| Prior catch | Current evidence | Status |
| --- | --- | --- |
| `cargo build --all` fails | `cargo build --all` passed on 2026-07-10. | Not a current blocker. |
| Mem0/Zep absent | Mem0 OSS exact-event ContinuityBench artifacts exist at `benchmarks/results/continuity/mem0-oss-exact.json` and `.md`; Zep/Graphiti still has no checked-in run artifact. | Partly resolved; Zep/Graphiti tracked by #13. |
| LoCoMo/LongMemEval absent | Official loaders exist in `benchmarks/shibahama_bench/tasks.py`, but no committed `locomo` or `longmemeval` result artifacts exist under `benchmarks/results`. | Still open; tracked by #2 and summary follow-up #3. |
| Recall graph is caller-map, not stored | Stored graph entities and relations exist in `core/src/storage.rs`; APIs expose `put_graph_entity`, `put_graph_relation`, `graph_snapshot`, `traverse_graph`, and `extract_subgraph`; recall has a stored-graph expansion test. | Not a current blocker. |
| Binding parity is smoke-only | Python and Node bindings expose practical APIs and smoke tests, but there is no committed parity matrix against Rust core coverage. | Still open; tracked by #14. |

## Remaining Tracked Work

- #2: Phase C official LoCoMo and LongMemEval-S benchmark artifacts.
- #3: Cross-reference standard benchmark numbers against ContinuityBench after #2.
- #4: TestPyPI/PyPI publish.
- #5: npm publish.
- #6: v0.1.0 cross-registry release.
- #7: ContinuityBench citable archive submission.
- #8: Three production or production-like deployments.
- #9: Stage 2 learned-policy runtime experiment.
- #10: Stage 3 constrained learned-policy training.
- #11: Learned-policy comparison against deterministic significance.
- #13: Zep/Graphiti external benchmark anchor.
- #14: Python/Node binding parity beyond smoke coverage.

## Stale Blockers Removed

- `cargo build --all` failure is not carried forward.
- Stored graph support is not carried as a blocker.
- Mem0 is not carried as absent for ContinuityBench; only Zep/Graphiti remains open.
