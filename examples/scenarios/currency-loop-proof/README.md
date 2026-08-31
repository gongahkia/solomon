# Currency Loop Proof

This headless, synthetic scenario proves the authority-change lifecycle without a model call or external service. It uses the supported Solomon service and MCP runtime interfaces.

```bash
uv run python examples/scenarios/currency-loop-proof/run.py --workspace /tmp/solomon-currency-loop-proof
```

The workspace must be empty. The run emits two artifacts:

- `currency-loop-proof-result.json` is the machine-readable result, including the measured local latency.
- `currency-loop-proof-snapshot.json` is the deterministic semantic snapshot used in CI.

The scenario creates one authority, two human-confirmed direct citation edges, one transitive dependent, a cycle-safety edge, and an unrelated item in a separate matter/client scope. It records an authority event, demonstrates default retrieval withholding stale items and review-mode explanations, verifies two items, supersedes one with a live successor, confirms historical recall, verifies an audit pack, then restarts the service and replays the event. It flags impacts for human review; it does not adjudicate the authority change.
