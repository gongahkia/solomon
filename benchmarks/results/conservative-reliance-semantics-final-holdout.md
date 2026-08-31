# Conservative Reliance Semantics Evaluation

Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.

- corpus version: `1.0.0`
- manifest SHA-256: `3e2757e6fe7e47e0c5af0629db16fa9c42f596a292079a7f0e33efaebb1d6820`
- split: `holdout` (40 base fixtures)
- runtime: `197.85` ms
- repeat-run determinism: `True`

## Aggregate metrics

| Metric | Value | Raw count |
| --- | ---: | ---: |
| reference precision | 0.75 | 30/40 |
| reference recall | 0.769231 | 30/39 |
| target resolution precision | 0.75 | 30/40 |
| target resolution recall | 0.769231 | 30/39 |
| suggestion precision | 1.0 | 12/12 |
| suggestion recall | 0.8 | 12/15 |
| exact evidence span accuracy | 0.8 | 12/15 |
| overlap or containment span accuracy | 0.8 | 12/15 |
| abstention accuracy | 1.0 | 25/25 |
| hard negative false positive rate | 0.0 | 0/16 |
| duplicate suggestion rate | 0.0 | 0/12 |
| suggestions per 100 items | 30.0 | 1200/40 |
| false positive suggestions per 100 items | 0.0 | 0/40 |
| cross scope leakage count | 0.0 | 0/1 |
| pre review confirmed edge count | 0.0 | 0/1 |

## Per-category results

| Category | Items | Suggestion P/R | Abstention | FP rate |
| --- | ---: | --- | ---: | ---: |
| alternative procedure | 1 | 1.0/1.0 | 1.0 | 1.0 |
| bare under | 1 | 1.0/1.0 | 1.0 | 1.0 |
| conditional reliance | 1 | 1.0/1.0 | 1.0 | 0.0 |
| consideration not reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| counterparty attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| court attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| cross sentence adoption | 1 | 1.0/1.0 | 1.0 | 1.0 |
| cross sentence rule anchor | 1 | 1.0/0.0 | 1.0 | 1.0 |
| derivation named artifact | 1 | 1.0/1.0 | 1.0 | 1.0 |
| direct required by after actor | 1 | 1.0/1.0 | 1.0 | 1.0 |
| follows for | 1 | 1.0/0.0 | 1.0 | 1.0 |
| having regard to | 1 | 1.0/1.0 | 1.0 | 1.0 |
| heading only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| independent assessment | 1 | 1.0/1.0 | 1.0 | 0.0 |
| multiple authorities unbound | 1 | 1.0/1.0 | 1.0 | 1.0 |
| no longer relies | 1 | 1.0/1.0 | 1.0 | 0.0 |
| opponent attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| potential reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| prior document reference | 1 | 1.0/1.0 | 1.0 | 0.0 |
| pursuant to operational | 1 | 1.0/1.0 | 1.0 | 1.0 |
| qualified follows | 1 | 1.0/1.0 | 1.0 | 1.0 |
| quoted report | 1 | 1.0/1.0 | 1.0 | 0.0 |
| rather than negation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| reference heading | 1 | 1.0/1.0 | 1.0 | 1.0 |
| regulator attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| rejected approach | 1 | 1.0/1.0 | 1.0 | 1.0 |
| replacement historical only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| replacement selected authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| reported prior draft | 1 | 1.0/1.0 | 1.0 | 1.0 |
| section symbol equivalence | 1 | 1.0/1.0 | 1.0 | 1.0 |
| subject to named advice | 1 | 1.0/1.0 | 1.0 | 1.0 |
| table reference | 1 | 1.0/1.0 | 1.0 | 0.0 |
| training extract | 1 | 1.0/1.0 | 1.0 | 1.0 |
| treats controlling | 1 | 1.0/0.0 | 1.0 | 1.0 |
| truncated authority | 1 | 1.0/1.0 | 1.0 | 0.0 |
| unregistered authority | 1 | 1.0/1.0 | 1.0 | 0.0 |
| upper case equivalence | 1 | 1.0/1.0 | 1.0 | 1.0 |
| uses as rule | 1 | 1.0/1.0 | 1.0 | 1.0 |
| witness attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| wrapped whitespace equivalence | 1 | 1.0/1.0 | 1.0 | 1.0 |

## Error-stage distribution

| Stage | Count |
| --- | ---: |
| reference not detected | 11 |
| reliance cue not recognized | 1 |
