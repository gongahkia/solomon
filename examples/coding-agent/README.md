# Coding Agent Example

This runnable demo uses Shibahama as memory for a deterministic coding agent.

Run:

```bash
python examples/coding-agent/run.py
```

The script seeds a realistic multi-session repo history:

- a rejected global singleton-store approach,
- an old file path for recall ranking,
- a later file move to `core/src/retrieval.rs`.

It then runs the same two scenarios against Shibahama and an append-only warehouse baseline:

- Scenario A: the agent avoids re-suggesting the rejected singleton-store approach.
- Scenario B: the agent re-validates the moved file before citing the current path.

Outputs:

- `out/results.json`: side-by-side scenario results.
- `out/tideline-recording.json`: a Tideline-shaped recording for demo replay material.
