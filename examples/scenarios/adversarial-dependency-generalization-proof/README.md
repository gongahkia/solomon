<!-- SPDX-License-Identifier: Apache-2.0 -->

# Adversarial Dependency Generalization Proof

This deterministic, headless scenario uses fictional evidence to exercise parser decisions and the canonical
`SolomonService` lifecycle. It is an engineering safety proof, not legal advice, legal validation, or a claim that
the fixed synthetic challenge corpus has passed every quality gate.

Run it in an empty workspace:

```bash
uv run python examples/scenarios/adversarial-dependency-generalization-proof/run.py \
  --workspace /tmp/solomon-adversarial-dependency-proof
```

It proves a direct and a cross-sentence candidate; quote, negation, and ambiguous abstention; one supported authority
among several; a stable heading-format mutation; unchanged-document deduplication; rejected-evidence suppression;
revision provenance; tenant isolation; no edge before review; exactly one human confirmation; currency impact only
from the confirmed edge; and journal/audit-pack verification. The snapshot excludes random IDs and timing so the test
is reproducible.
