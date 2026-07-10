# Learned-Policy Stage 1 Local Evaluation

Issue: https://github.com/gongahkia/shibahama/issues/11

Artifact: `benchmarks/results/learned-policy-stage1-local.json`

Held-out continuity source:

- dataset: `benchmarks/continuity/dataset/continuitybench-v0.json`
- dataset hash: `sha256:a68d3f55a21b3ad0799f4c10e28e02a53b4cac2e39e5679df214323ad961bfaa`
- source result artifact: `benchmarks/results/continuity/shibahama.json`

## Config

Deterministic baseline: `significance-v0`, promote at materialized
significance `>= 2.0`, demote below `0.5`, and clamp demotion to
`credence_floor`.

Candidate policy: `stage1-naive-candidate-v0`. No model was trained, no runtime
mutation was allowed, and the action space excluded delete, overwrite, and
destructive mutation.

## Result

| Metric | Value |
| --- | ---: |
| labeled decisions | 4 |
| candidate score | 0.00 |
| deterministic baseline score | 2.25 |
| score margin | -2.25 |
| invariant violations | 0 |

Recommendation: `StopBaselineNotBeaten`.

Conclusion: deterministic significance is sufficient; RL not justified.

## Invariant Evidence

Property command:

```sh
python3 -m pytest benchmarks/test_learned_policy_artifact.py
```

The test validates the committed action trace for never-delete preservation,
source-lineage preservation, credence-floor preservation, and pinned-memory
floor preservation.
