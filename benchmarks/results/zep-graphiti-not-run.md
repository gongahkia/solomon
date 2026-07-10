# Zep/Graphiti Benchmark Anchor Status

Issue: https://github.com/gongahkia/shibahama/issues/13

Status: not run.

Target dataset:

- `benchmarks/continuity/dataset/continuitybench-v0.json`
- `sha256:a68d3f55a21b3ad0799f4c10e28e02a53b4cac2e39e5679df214323ad961bfaa`

No reproducible local or self-hosted Zep/Graphiti setup, service version,
credentials state, and dataset-permission manifest is committed in this repo.
Therefore there is no Zep/Graphiti metric comparison and no token-cost
accounting artifact.

Before a real run lands, it must include:

- adapter implementation and dependency instructions;
- local or self-hosted setup path;
- service or package version;
- credential and dataset-permission manifest;
- exact command;
- generated JSON and Markdown result artifacts;
- metric comparison against Shibahama, warehouse, and full-context on the
  identical slice;
- token-cost accounting where available.

Unsupported claims omitted:

- Shibahama beats Zep/Graphiti on LoCoMo.
- Shibahama beats Zep/Graphiti on LongMemEval.
- Shibahama beats Zep/Graphiti on ContinuityBench.
