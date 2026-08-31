<!-- SPDX-License-Identifier: Apache-2.0 -->

# Conservative Reliance Semantics: Untuned Baseline

This baseline was generated after the independent corpus lock `ed10589` and before the one permitted production
experiment. It uses the inherited deterministic parser frozen at `a21263c`; the new evaluation script and corpus
integrity helper do not participate in extraction. Every record is parser-only: it creates no persisted, confirmed,
or propagated edge.

## Controls

The pre-existing 23-fixture Evidence-to-Dependency control corpus remained exact: authority-reference precision and
recall, suggestion precision and recall, exact/overlap raw evidence spans, and abstention were all `1.000`, with zero
errors, duplicates, scope leakage, or pre-review confirmations. Its raw record is
[`evidence-to-dependency-conservative-reliance-baseline-control.json`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/evidence-to-dependency-conservative-reliance-baseline-control.json).

## New independent corpus

The new corpus is version `1.0.0`, SHA-256
`3e2757e6fe7e47e0c5af0629db16fa9c42f596a292079a7f0e33efaebb1d6820`, with 24 development and 40 locked-holdout
fixtures. Its baseline has already been recorded in full so the later frozen implementation can be compared honestly.
The holdout is not used to select grammar changes.

| Measure | Development (24) | Holdout (40) | All (64) |
| --- | ---: | ---: | ---: |
| Reference precision / recall | 0.923 / 0.960 | 0.900 / 0.923 | 0.909 / 0.938 |
| Target-resolution precision / recall | 0.923 / 0.960 | 0.900 / 0.923 | 0.909 / 0.938 |
| Suggestion precision / recall | 0.571 / 0.444 | 0.429 / 0.200 | 0.500 / 0.292 |
| Exact raw evidence span accuracy | 0.444 | 0.200 | 0.292 |
| Overlap/containment span accuracy | 0.444 | 0.200 | 0.292 |
| Abstention accuracy | 0.800 | 0.840 | 0.825 |
| Hard-negative false-positive rate | 0.125 | 0.188 | 0.167 |
| False-positive suggestions / 100 fixtures | 12.50 | 10.00 | 10.94 |
| Duplicate suggestion rate | 0.000 | 0.000 | 0.000 |

Both runs were repeat-run deterministic, and their parser-only safety counters were all zero. The baseline does not
meet the new contract, particularly on abstention, hard-negative false positives, direct grammar coverage, raw span
accuracy, wrapped whitespace, and case-independent authority parsing.

Development residuals are five missed affirmative constructions (`relies on`, adoption, grounded-in, derives-from,
and subject-to), one client-attribution false positive, and two instruction/incomplete-proposition false positives.
The holdout baseline independently exposes misses for case, wrapped whitespace, direct and adoption forms, and three
reference-label misses; it also falsely proposes from a witness quotation, client conditional, bare `under`, and
`no longer relies` sentence. These raw errors are retained in the machine-readable records; none is silently
relabelled.

Raw records: [development](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/conservative-reliance-semantics-baseline-development.json),
[holdout](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/conservative-reliance-semantics-baseline-holdout.json),
and [all fixtures](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/conservative-reliance-semantics-baseline-all.json).
