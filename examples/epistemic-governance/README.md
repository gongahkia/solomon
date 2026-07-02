# Epistemic Governance Demo

Runs a deterministic coding-agent scenario where a stale API fact is invalidated
and replaced before the agent answers again.

```sh
python examples/epistemic-governance/run.py
```

The demo prints the before/after answer, the superseded and current memory ids,
valid-time evidence, current credence, and event kinds.
