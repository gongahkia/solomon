<!-- SPDX-License-Identifier: Apache-2.0 -->

# Adversarial Dependency Generalization Proof

## Outcome

The deterministic dependency extractor substantially improved against the locked synthetic challenge, but it does
**not** pass the complete predeclared holdout gate. This is an engineering result, not a legal-quality claim. No third
extractor hypothesis was attempted after the two allowed deterministic changes.

The challenge corpus is version `1.0.0`, SHA-256
`bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256`, and is composed of 84 independently authored
fictional fixtures: 32 development, 52 locked holdout, 35 dependencies, 32 hard negatives, 17 ambiguous cases, and
12 fixed label-preserving mutations. Its schema, integrity validator, hash, and protocol were committed before any
challenge extraction in `cb12eb9`.

The pre-change baseline, including raw errors and counts, is documented in
[the baseline record](adversarial-dependency-generalization-baseline.md). Baseline holdout suggestion precision/recall
were 0.643/0.450, exact evidence-span accuracy was 0.450, and fixed-mutation stability was 0.833.

## Final frozen evaluation

The final implementation is commit `5bd784d`. The existing 23-fixture Evidence-to-Dependency control corpus remains
at 1.0 for all of its reported reference, suggestion, evidence-span, and abstention metrics, with no errors. Fresh
raw output is
[`evidence-to-dependency-adversarial-final-regression.json`](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/evidence-to-dependency-adversarial-final-regression.json).

| Predeclared holdout gate | Final value | Status |
| --- | ---: | --- |
| Suggestion precision ≥ 0.90 | 1.000 (16/16) | pass |
| Suggestion recall ≥ 0.70 | 0.800 (16/20) | pass |
| Exact evidence-span accuracy ≥ 0.90 | 0.800 (16/20) | **fail** |
| Containment/overlap ≥ 0.98 | 0.800 (16/20) | **fail** |
| Abstention accuracy ≥ 0.85 | 1.000 (34/34) | pass |
| Hard-negative false-positive rate ≤ 0.10 | 0.000 (0/20) | pass |
| Mutation label stability ≥ 0.95 | 0.833 (10/12) | **fail** |
| Repeat-run determinism | true | pass |
| Duplicate suggestion rate | 0.000 (0/16) | pass |

Development evaluation is stronger (precision 1.000, recall 0.944, exact/overlap 0.944, abstention 1.000,
hard-negative FP 0.000), but it is not substituted for the held-out result. The final holdout and mutation runs were
executed after the frozen production commit; no later production parsing change was made.

Raw machine-readable output and human-readable renderings:

- [final development JSON](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-final-development.json) and [report](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-final-development.md)
- [final holdout JSON](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-final-holdout.json) and [report](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-final-holdout.md)
- [final mutation JSON](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-final-mutations.json) and [report](https://github.com/gongahkia/solomon/blob/main/benchmarks/results/adversarial-dependency-challenge-final-mutations.md)

## Bounded experiment history

Only these two production hypotheses were retained. Neither uses an LLM fallback or bypasses human review.

| Hypothesis | Targeted stage | Mechanism and false-positive risk | Development result | Regression / final holdout result |
| --- | --- | --- | --- | --- |
| H1: citation-span and form recognition | `reference_not_detected`, `evidence_span_over_broad` | Preserve the raw authority slice while normalizing only its ID; recognize one parenthesized provision suffix, `Guidance` as an authority noun, declared acronym aliases, and exclude `Under` from a title. Risk: a declared alias can add a candidate; only a local `ALIAS denotes Title N` declaration qualifies. | Suggestion P/R improved from 0.833/0.556 to 0.929/0.722; exact span 0.722; hard-negative FP remained 0.083. | Existing control remained 1.0. The final combined holdout result is 1.000/0.800 P/R and 0.800 exact span. |
| H2: bounded adoption and anaphoric cross-sentence evidence | `reliance_cue_not_recognized`, `cross_sentence_relationship_missed`, attributed false positives | Add explicit adoption patterns (`supplies`, `provides`, `sets`, `establishes`, `uses … as`, `treats … as`, `follows … for`, `source of`) and join only an immediately preceding sentence that contains `adopt`; reject stated third-party positions. Risk: broader cue coverage can over-propose; attribution and existing local negation guards remain required. | Final development P/R 1.000/0.944; exact span 0.944; abstention 1.000; hard-negative FP 0.000. | Existing control remained 1.0. The final combined holdout result above has zero hard-negative false positives, but retains four missed suggestions/spans. |

The final failures are recorded rather than hidden. Two mutation failures remain: expanded whitespace removes the
`relies on` cue match (`mut-01`), and all-case input loses the title boundary (`mut-08`). The residual holdout misses
are two table-of-authorities references, one authority-like workbook title, an `establishes … used by` construction,
a parenthetical intervening after `required by`, a replacement construction, and a qualified `follows` construction.
The last four account for the 16/20 final suggestion/span result. These are candidates for a later separately
predeclared proof, not grounds to change this locked result.

## Safety and lifecycle evidence

The corpus evaluator calls only deterministic extraction and suggestion creation in memory. It cannot create,
confirm, or propagate an edge. Its machine-readable safety fields therefore record zero persistence effects by
construction; the service-level claims below are independently demonstrated rather than inferred from parser output.

[`examples/scenarios/adversarial-dependency-generalization-proof/run.py`](https://github.com/gongahkia/solomon/blob/main/examples/scenarios/adversarial-dependency-generalization-proof/run.py)
uses the canonical `SolomonService`, synthetic material only, and writes a deterministic snapshot plus audit pack. It
proves all of the following in one headless path:

- direct and cross-sentence candidate creation with reconstructible evidence;
- abstention for a quotation, negation, and ambiguous short form;
- only one suggestion when a second authority is background-only;
- target stability for a heading-format mutation;
- zero edges before review, exactly one confirmed edge, and rejected/deferred decisions;
- duplicate document ingestion, suppression of rejected unchanged evidence, and revision provenance;
- rejection of a cross-tenant confirmation and exclusion from the other tenant’s queue;
- a fictional authority change stales only the confirmed item; pending, rejected, and deferred items remain live; and
- journal and exported audit-pack verification.

Run it with:

```bash
uv run python examples/scenarios/adversarial-dependency-generalization-proof/run.py \
  --workspace /tmp/solomon-adversarial-dependency-proof
```

The committed snapshot test is
[`tests/test_adversarial_dependency_demo.py`](https://github.com/gongahkia/solomon/blob/main/tests/test_adversarial_dependency_demo.py). It validates semantic
invariants rather than random IDs or runtime values.

## Limits and follow-up

This is synthetic engineering evidence. It does not establish external generalization, legal correctness, citation
coverage, user understanding, confidentiality compliance, or a law-firm’s operational readiness. It does not alter
the existing owner-operated pilot status: pilot execution and observations remain pending. The holdout corpus must not
be edited to fit the implementation; an objectively malformed fixture requires a recorded version/hash change and a
comparability note.

## Later conservative-reliance addendum

The later reversible normalized-analysis/declarative-grammar experiment is recorded separately in
[Conservative Reliance Semantics Proof](conservative-reliance-semantics.md). Its new corpus performed safely, but the
experiment violated this locked corpus’s immutable precision, abstention, and hard-negative false-positive conditions;
the production source was reverted rather than retuned.
