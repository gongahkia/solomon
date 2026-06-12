<!-- SPDX-License-Identifier: Apache-2.0 -->

# Solomon Currency Evaluation

Version: `v0.1.0`  
Date: 2026-06-11

## Abstract

Solomon evaluates whether internal firm knowledge is still current by combining dependency graphs,
bi-temporal storage, credence tiers, and verification state. This evaluation compares Solomon against a
similarity-only warehouse baseline and a decay-style baseline on synthetic firm knowledge where old knowledge
can remain correct and recent knowledge can be unsafe.

## Method

The released corpus generator creates:

- internal knowledge items with provenance and credence tiers;
- dependency edges from internal items to an external authority;
- an oracle set of items expected to become stale after that authority moves;
- baselines that ignore dependency movement or incorrectly rely on age.
- jurisdiction-pack cases covering the vendored boundary's supported jurisdictions;
- before/after external-authority snapshot fixtures for monitoring replay and propagation.

Reproduce the corpus:

```bash
uv run python scripts/export_synthetic_corpus.py --size 10 --output docs/evaluation-corpus.synthetic.json
```

Run the evaluation harness:

```bash
uv run python -m solomon.evaluation
```

## Metrics

| Metric | Meaning |
|---|---|
| Stale-surface rate | Fraction of surfaced items that are stale or superseded. |
| Time-to-flag | Seconds between dependency change ingestion and stale flag. |
| Impact-query recall | Fraction of oracle stale items returned by an impact query. |

## Current Result Shape

The deterministic harness is small by design, but it now includes three measurable result groups: currency
correctness, vendored jurisdiction coverage, and external-law monitoring fixture replay.

| System | Expected behavior |
|---|---|
| Solomon | Flags dependency-driven stale items and keeps stale/superseded content out of default recall. |
| Warehouse baseline | Retrieves similar text with no staleness signal. |
| Decay baseline | Penalizes age even when age is not the legal validity signal. |
| Jurisdiction coverage | Exercises every vendored jurisdiction pack and reports missing packs or missing expected findings. |
| External-law monitoring replay | Diffs before/after authority snapshots, reports change-detection recall and false positives, then propagates detected changes into impact-query recall. |

## Limitations

- The core firm-knowledge corpus is synthetic.
- The external-law monitoring benchmark is fixture replay; it does not claim live source coverage comparable
  to a citator or legal research platform.
- The dependency graph oracle is curated.
- The evaluation tests Solomon's product thesis: currency beats recency for firm knowledge.

## Citation

Use the repository `CITATION.cff` entry or cite this writeup as:

> Solomon contributors. Solomon Currency Evaluation. Version v0.1.0. 2026-06-11.
