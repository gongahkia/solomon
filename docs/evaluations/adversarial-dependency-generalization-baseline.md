<!-- SPDX-License-Identifier: Apache-2.0 -->

# Adversarial Dependency Challenge: Untuned Baseline

The raw machine-readable records in [`benchmarks/results`](https://github.com/gongahkia/solomon/tree/main/benchmarks/results) capture the deterministic
extractor state inherited from `f8f5a18`, after the separate corpus-lock commit `cb12eb9` and before an adversarial
production hypothesis. The evaluator itself does not persist, confirm, or propagate a suggestion.

## Regression control

The existing 23-fixture Evidence-to-Dependency corpus was rerun without changing its manifest. Its complete metrics
remain 1.0 for reference precision/recall, suggestion precision/recall, exact and overlap evidence spans, and
abstention; it recorded no errors, duplicates, cross-scope leakage, or pre-review confirmed edges. The fresh raw
record is [`evidence-to-dependency-adversarial-regression.json`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/evidence-to-dependency-adversarial-regression.json).

## Challenge measurement

The corpus is `1.0.0`, hash
`bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256`. Baseline runs are split before any
extractor change; generated variants are a separate denominator.

| Measure | Development (32) | Holdout (52) | All base fixtures (84) |
| --- | ---: | ---: | ---: |
| Reference precision / recall | 0.818 / 0.771 | 0.860 / 0.827 | 0.843 / 0.805 |
| Target-resolution precision / recall | 0.879 / 0.829 | 0.860 / 0.827 | 0.867 / 0.828 |
| Suggestion precision / recall | 0.833 / 0.556 | 0.643 / 0.450 | 0.731 / 0.500 |
| Exact evidence span accuracy | 0.444 | 0.450 | 0.447 |
| Overlap/containment span accuracy | 0.444 | 0.450 | 0.447 |
| Abstention accuracy | 0.933 | 0.941 | 0.939 |
| Hard-negative false-positive rate | 0.083 | 0.100 | 0.094 |
| False-positive suggestions / 100 fixtures | 6.25 | 9.62 | 8.33 |
| Duplicate-suggestion rate | 0.000 | 0.000 | 0.000 |

Fixed-mutation label stability is 0.833 (10/12), below the predeclared 0.95 gate. All repeated-run determinism
checks were true. The parser-only evaluator reports zero persisted lifecycle outcomes by construction; the later
headless service scenario, not this corpus pass, must prove scope filtering, rejection suppression, confirmation, and
currency boundaries.

Raw records: [`development`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-baseline-development.json),
[`holdout`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-baseline-holdout.json),
[`all`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-baseline-all.json), and
[`mutations`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-baseline-mutations.json).

## Stage-level error analysis

The 84-fixture aggregate has 45 recorded discrepancies. A fixture can have a reference and a downstream suggestion
discrepancy, so this is a stage ledger rather than a fixture count.

| Stage | Count | Bounded interpretation | Planned treatment |
| --- | ---: | --- | --- |
| `reference_not_detected` | 27 | The narrow grammar drops provision suffixes, `Guidance` titles, aliases, or original whitespace spans. | Hypothesis 1: preserve source spans and extend bounded legal-form recognition. |
| `reliance_cue_not_recognized` | 6 | The sentence has a labeled adoption construction outside the current cue list. | Hypothesis 2: add explicit, attribution-aware adoption constructions. |
| `cross_sentence_relationship_missed` | 3 | The current evidence window stops at a sentence or paragraph boundary. | Hypothesis 2: permit only an immediately adjacent, anaphorically anchored authority sentence. |
| `mention_mistaken_for_reliance` | 4 | A broad cue can attach to a nearby but unlabeled authority. | Hypothesis 2 must reduce this risk; it may not trade away a hard-negative class. |
| `quoted_or_attributed_position_mistaken_for_firm_reliance` | 3 | The parser treats another speaker’s position as the firm’s reliance. | Hypothesis 2 must reject explicit third-party attribution. |
| `evidence_span_over_broad` | 2 | Extraction normalized citation text instead of preserving the exact source evidence. | Hypothesis 1: retain the original authority slice while normalizing only the ID. |

The hard-negative rate is exactly at the predeclared holdout ceiling (0.10), while holdout precision, recall, and
span metrics miss their gates. The baseline therefore supports bounded deterministic experiments, not a claim of
generalization.
