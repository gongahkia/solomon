<!-- SPDX-License-Identifier: Apache-2.0 -->

# Conservative Reliance Semantics Proof

## Decision

**Rejected.** The single permitted normalized-analysis/declarative-grammar experiment was frozen at `65a5853` and
evaluated once against each locked holdout. Although its new-corpus precision and abstention behavior were strong, it
missed the new overlap gate and, critically, violated the immutable existing-84 safety conditions. The production
source was reverted in `6164c9e`. This is a negative engineering result, not a claim about legal language or legal
correctness.

The starting state was `a21263c`, following the prior two-hypothesis adversarial proof. Its exact reproduced residuals
are in [the pre-change report](conservative-reliance-semantics-residuals.md). The independent corpus lock is
`ed10589`, the pre-change baseline record is `e50a1c8`, the only production experiment is `65a5853`, and the required
revert is `6164c9e`. No second parser hypothesis was tried.

## Locked corpus and baseline

The new corpus is `solomon.conservative_reliance_semantics_corpus.v1`, version `1.0.0`, SHA-256
`3e2757e6fe7e47e0c5af0629db16fa9c42f596a292079a7f0e33efaebb1d6820`: exactly 64 independently authored fictional
fixtures, split 24 development/40 locked holdout, with 24 affirmative reliance fixtures, 24 hard negatives, and 16
ambiguous fixtures. Its [corpus card](conservative-reliance-semantics-corpus-card.md) and hash verifier were committed
before extraction changes. The original 84-fixture adversarial corpus remains independently locked at SHA-256
`bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256`.

The inherited baseline on the new corpus was weak: development/holdout suggestion precision was 0.571/0.429, recall
0.444/0.200, abstention 0.800/0.840, and hard-negative false-positive rate 0.125/0.188. The existing 23-fixture
control was exact. Full baseline records and uncollapsed errors are in
[the baseline report](conservative-reliance-semantics-baseline.md).

## Development and frozen mutation evidence

Before freeze, the sole implementation passed the existing 23-fixture control exactly. On the new 24-fixture
development split it achieved suggestion precision/recall 1.000/1.000, exact and overlap raw evidence spans 1.000,
abstention 1.000, zero hard-negative false positives, zero duplicate suggestions, zero false positives per 100
fixtures, and repeat-run determinism. The existing adversarial development split had precision 1.000, recall 0.833,
abstention 1.000, and zero hard-negative false positives. All twelve existing fixed mutations were stable (1.000),
including whitespace expansion and case variation. These development measurements did not authorize a holdout edit or
another grammar change.

## Frozen locked-holdout results

### New 40-fixture holdout

| Predeclared gate | Frozen value | Status |
| --- | ---: | --- |
| Suggestion precision ≥ 0.95 | 1.000 (12/12) | pass |
| Suggestion recall ≥ 0.80 | 0.800 (12/15) | pass |
| Exact raw evidence span ≥ 0.80 | 0.800 (12/15) | pass |
| Overlap/containment span ≥ 0.90 | 0.800 (12/15) | **fail** |
| Abstention ≥ 0.95 | 1.000 (25/25) | pass |
| Hard-negative FP rate ≤ 0.05 | 0.000 (0/16) | pass |
| Duplicate suggestions | 0 | pass |
| Repeat-run deterministic | true | pass |

The three missed affirmative spans were `sem-hold-02` (follows-for), `sem-hold-04` (treats-controlling), and
`sem-hold-10` (cross-sentence rule anchor). Raw reference misses also remain in the machine record for several
abstention fixtures. Those misses explain the exact/overlap shortfall; no false-positive suggestion was hidden.

### Existing locked 84-fixture adversarial holdout

| Immutable condition | Required | Frozen value | Status |
| --- | ---: | ---: | --- |
| Suggestion precision | exactly 1.000 | 0.850 (17/20) | **fail** |
| Suggestion recall | ≥ 0.800 | 0.850 (17/20) | pass |
| Exact raw evidence span | ≥ 0.800 | 0.850 (17/20) | pass |
| Abstention | exactly 1.000 | 0.912 (31/34) | **fail** |
| Hard-negative false positives | exactly 0 | 2/20 | **fail** |
| False positives / 100 fixtures | exactly 0 | 5.769 (3/52) | **fail** |
| Duplicate suggestions | 0 | 0 | pass |
| Mutation stability | ≥ 0.833 | 1.000 (12/12) | pass |

The three false suggestions were a hypothetical “would matter” (`adv-hold-18`), an ambiguous “refers to” sentence
(`adv-hold-35`), and an attributed opposing submission (`adv-hold-51`). The other three missing affirmative
suggestions were `adv-hold-04`, `adv-hold-06`’s second authority, and `adv-hold-08`. The full machine record retains
every raw expected/actual span and all reference discrepancies.

Raw frozen outputs: [new holdout JSON](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/conservative-reliance-semantics-final-holdout.json),
[new holdout report](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/conservative-reliance-semantics-final-holdout.md),
[existing-84 holdout JSON](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-conservative-reliance-final-holdout.json),
[existing-84 holdout report](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-conservative-reliance-final-holdout.md),
[final exact control](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/evidence-to-dependency-conservative-reliance-final-control.json),
and [final mutation record](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-conservative-reliance-final-mutations.json).

## Raw mapping and safety result

[The reversible-mapping record](conservative-reliance-semantics-mapping.md) describes the one canonical analysis view,
the fingerprint policy, mapped whitespace/quotes/section symbols, guard/explanation format, and property coverage.
Every candidate emitted by the rejected experiment carried its original raw evidence slice and raw authority slice;
the evidence was not rewritten for review. The evaluators remained parser-only and reported zero scope leakage,
pre-review confirmation, persistence, propagation, rejected-evidence resurfacing, or non-confirmed currency effects.

The experiment did not change the existing lifecycle: suggestions remain deterministic review candidates, confirmation
remains human-only, and the revert leaves no new automatic edge path. Existing evidence-proof, currency-loop, and
adversarial scenarios remain the service-level lifecycle evidence. A new affirmative scenario is intentionally not
retained because its parser prerequisite failed the locked safety gate.

## Stop decision and one next milestone

The protocol’s stop condition applies: do not expand this parser again or tune it to either holdout. The retained
corpus, annotations, baseline, failed measurements, mapping record, and documentation are evidence for the next
audit, while the rejected source remains visible in Git history and is absent from the current implementation.

The one recommended next milestone is a **bounded human-authored reliance form**: let a reviewer explicitly select an
already registered authority, record a raw supporting span and rationale, and create only the existing human-reviewed
candidate. It should be evaluated as a separate product/workflow proof, not as another parser expansion.
