# ContinuityBench Citable Submission

Submitting ContinuityBench somewhere citable is externally blocked until a release
owner signs in to the chosen archive and approves the release metadata. The repo
is prepared for a Zenodo-backed DOI through `.zenodo.json` and `CITATION.cff`.

## Recommended Path

Use GitHub-to-Zenodo release archiving:

1. Enable Zenodo archiving for `gongahkia/shibahama`.
2. Confirm `.zenodo.json` metadata is accepted.
3. Create the final `v0.1.0` GitHub release after registry publish succeeds.
4. Let Zenodo archive the release and mint the DOI.
5. Add the DOI to `CITATION.cff`, this file, and `benchmarks/continuity/README.md`.

## Submission Scope

Submit the repository release, not a standalone claim that ContinuityBench is a
large public benchmark. The current citable artifact should be described as:

```text
ContinuityBench v0 is a synthetic, templated benchmark included with
Shibahama. It measures stale-answer rate, contradiction resolution,
evidence-quality calibration, stable recall, and retrieved-token cost on
mutable long-lived memory tasks. Checked-in baselines cover Shibahama,
warehouse, full context, Mem0 OSS exact-event retrieval, and Engram exact-event
retrieval.
```

## Pre-Submission Checklist

- `benchmarks/continuity/dataset/continuitybench-v0.json` has canonical hash
  `sha256:a68d3f55a21b3ad0799f4c10e28e02a53b4cac2e39e5679df214323ad961bfaa`.
- `benchmarks/results/continuity/SUMMARY.md` and
  `benchmarks/results/SUMMARY.md` match their checked-in JSON artifacts.
- The Phase C LoCoMo and LongMemEval-S rows cited in
  `benchmarks/results/SUMMARY.md` are limited to their committed artifacts.
- No unsupported hosted-system, performance, or leaderboard claim is present.
- `CITATION.cff` and `.zenodo.json` metadata match the release title and
  version.
