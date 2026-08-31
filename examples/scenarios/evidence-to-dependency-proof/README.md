# Evidence-to-Dependency Proof

This deterministic, headless scenario uses fictional legal-style material. It proves a controlled path from a
source document and candidate claim to a pending suggestion with inspectable spans, human decisions, a confirmed
edge, and bounded currency impact. It is not legal advice or external-curator validation.

Run it in an empty workspace:

```bash
uv run python examples/scenarios/evidence-to-dependency-proof/run.py --workspace /tmp/solomon-evidence-to-dependency-proof
```

The scenario confirms one suggestion, rejects a quotation-derived mention, defers one unresolved suggestion,
re-ingests unchanged evidence, restarts, records a revised source-document version, denies a cross-scope decision,
and verifies its audit pack. Only the confirmed edge receives staleness when the fictional authority changes.
