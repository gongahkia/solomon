<!-- SPDX-License-Identifier: Apache-2.0 -->

# Adversarial Dependency Generalization Proof Protocol

## Question and boundary

This protocol tests whether the deterministic Evidence-to-Dependency rules generalize beyond the 23 controlled
regression fixtures. It measures fictional, independently authored challenge documents; it is neither legal advice,
law-firm validation, nor evidence that Solomon comprehensively extracts legal dependencies.

Solomon remains a review control plane: a reference is not a dependency, a suggestion is not an edge, and no model or
parser output can affect currency without an authorized human confirmation. Precision and abstention matter because a
false proposal consumes curator attention.

## Predeclared corpus rules

- Each base fixture is authored from the product contract and semantic taxonomy, not copied, paraphrased, mutated, or
  mechanically extended from the earlier 23-fixture corpus.
- All material is synthetic and fictional. Short citation *forms* may be realistic; no substantial legal text or firm
  material is included.
- Every fixture has a stable ID, scope, authority candidates, exact reference/evidence text spans, target labels,
  annotation rationale, expected suggestion count, and whether a human could legally confirm the relationship.
- A span is represented by its exact unique source substring. The loader independently resolves and validates its
  offsets before any extraction is run, preventing labels from depending on parser output.
- The manifest assigns development and holdout before evaluation. `holdout` is immutable after the challenge-lock
  commit. An objectively malformed fixture requires a documented version/hash change rather than a silent edit.
- The corpus includes at least 80 base fixtures: at least 24 `Depends`, 32 hard negatives, and 16 ambiguous or
  abstention cases. It uses 32 development and 48 locked-holdout fixtures.

## Stage separation and taxonomy

Evaluation reports these independent stages: reference detection; normalization; target resolution; reliance
classification; evidence-span reconstruction; suggestion creation; human confirmation; and currency propagation.
Only the first six are exercised by corpus extraction. Lifecycle and propagation are demonstrated through the existing
service proof and the adversarial scenario; corpus execution never confirms an edge.

Stable error categories are: `reference_not_detected`, `reference_boundary_incorrect`, `normalization_failure`,
`wrong_authority_target`, `scope_filter_error`, `reliance_cue_not_recognized`,
`cross_sentence_relationship_missed`, `mention_mistaken_for_reliance`,
`quoted_or_attributed_position_mistaken_for_firm_reliance`, `negation_missed`, `qualification_missed`,
`wrong_authority_associated_with_cue`, `evidence_span_incomplete`, `evidence_span_over_broad`,
`duplicate_not_collapsed`, `correct_candidate_removed_after_generation`, and `incorrect_fixture_or_ambiguous_annotation`.
Each error record includes expected and actual state, a bounded root-cause hypothesis, whether a deterministic remedy
appears possible, and false-positive risk.

## Metrics and curator burden

The evaluator reports reference, target-resolution, and suggestion precision/recall separately; exact and
containment/overlap span accuracy; abstention; hard-negative false-positive rate; suggestions and false-positive
suggestions per 100 items; duplicate rate; scope leakage; pre-review edges; repeat determinism; runtime; corpus size;
and raw numerator/denominator counts. It reports the same relevant measures per semantic category rather than hiding
weak categories behind an aggregate.

Mutation robustness is a separate denominator over a fixed mutation manifest. Generated variants never change the
base-corpus aggregate. The documented, label-preserving transformations use fixed seeds and comprise whitespace
expansion/collapse, line wrapping, quote conversion, punctuation, headings, footnote relocation, case variation,
section-symbol forms, parenthetical formatting, paragraph boundaries, and explicitly declared equivalent aliases.

## Safety invariants and quality gate

The following must remain zero: cross-scope leakage; pre-review confirmed edges; non-determinism; duplicate pending
suggestions from unchanged ingestion; rejected unchanged evidence resurfacing; currency impact from pending/rejected/
deferred suggestions; and privileged action caused by instruction-like text.

The predeclared locked-holdout engineering gate is: suggestion precision >= `0.90`, suggestion recall >= `0.70`, exact
evidence-span accuracy >= `0.90`, containment/overlap >= `0.98`, abstention >= `0.85`, hard-negative false-positive
rate <= `0.10`, and mutation label stability >= `0.95`. These are bounded curator-review gates, not legal-adequacy
claims. They are fixed before baseline evaluation and will not be loosened after observing results.

## Change and correction rules

The challenge-lock commit contains this protocol, corpus, loader, integrity checker, mutation manifest, and corpus
card only. It contains no production extractor change. The untuned `f8f5a18` behavior is then recorded on the old
corpus, challenge development/holdout, and mutation suite.

At most two deterministic production hypotheses may be attempted. Each must name its target error class, expected
generalization mechanism, likely false-positive risk, development result, regression result, and one final holdout
result. It is retained only if safety holds, old-regression behavior remains sound, development improves as intended,
holdout precision does not materially regress, curator burden stays proportionate, and no material hard-negative class
is sacrificed. Failed changes are reverted while their results remain recorded. No LLM fallback is permitted.

## Completion and claim limits

Completion requires the committed hash-locked corpus, baseline/final raw outputs, category and error analysis,
mutation results, safety evidence, an adversarial headless scenario, and the existing proof regressions. An honest
gate failure is valid. Results remain synthetic engineering evidence; fictional or public-style citations do not prove
legal correctness, external generalization, curator usability, confidentiality compliance, or firm adoption. The
owner-operated pilot remains pending unless an owner actually records the protocol observations.
