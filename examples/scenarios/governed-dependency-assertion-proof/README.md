# Governed Dependency Assertion Proof

This deterministic, headless scenario demonstrates the governed assertion lifecycle using fictional material. It
does not assess the legal or factual correctness of the synthetic assertions. Solomon preserves, scopes, reviews,
and propagates explicitly asserted dependencies with reconstructible evidence and audit provenance.

Run it in an empty workspace:

```bash
uv run python examples/scenarios/governed-dependency-assertion-proof/run.py --workspace /tmp/solomon-governed-dependency-assertion-proof
```

The proof registers separate Alpha and Bravo document and authority sources, creates three explicit assertions
(human quotation, human commentary, and trusted-upstream commentary), and proves that creation creates no graph
edge. It rejects malformed quotes, a free-text external target, a missing target, and a cross-scope target; denies
self-confirmation; confirms the human assertion concurrently and on retry; rejects and defers the other assertions;
then withdraws the deferred assertion. It also proves scope-denied reads and mutations, preserves the confirmed edge
through a source-document revision while marking the assertion for re-verification, limits authority-change currency
impact to the confirmed assertion, and verifies the exported audit pack.
