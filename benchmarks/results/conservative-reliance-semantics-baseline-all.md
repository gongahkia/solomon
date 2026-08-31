# Conservative Reliance Semantics Evaluation

Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.

- corpus version: `1.0.0`
- manifest SHA-256: `3e2757e6fe7e47e0c5af0629db16fa9c42f596a292079a7f0e33efaebb1d6820`
- split: `all` (64 base fixtures)
- runtime: `244.974` ms
- repeat-run determinism: `True`

## Aggregate metrics

| Metric | Value | Raw count |
| --- | ---: | ---: |
| reference precision | 0.909091 | 60/66 |
| reference recall | 0.9375 | 60/64 |
| target resolution precision | 0.909091 | 60/66 |
| target resolution recall | 0.9375 | 60/64 |
| suggestion precision | 0.5 | 7/14 |
| suggestion recall | 0.291667 | 7/24 |
| exact evidence span accuracy | 0.291667 | 7/24 |
| overlap or containment span accuracy | 0.291667 | 7/24 |
| abstention accuracy | 0.825 | 33/40 |
| hard negative false positive rate | 0.166667 | 4/24 |
| duplicate suggestion rate | 0.0 | 0/14 |
| suggestions per 100 items | 21.875 | 1400/64 |
| false positive suggestions per 100 items | 10.9375 | 700/64 |
| cross scope leakage count | 0.0 | 0/1 |
| pre review confirmed edge count | 0.0 | 0/1 |

## Per-category results

| Category | Items | Suggestion P/R | Abstention | FP rate |
| --- | ---: | --- | ---: | ---: |
| adoption local | 1 | 1.0/0.0 | 1.0 | 1.0 |
| alternative authorities | 1 | 1.0/1.0 | 1.0 | 1.0 |
| alternative procedure | 1 | 1.0/1.0 | 1.0 | 1.0 |
| background table | 1 | 1.0/1.0 | 1.0 | 0.0 |
| bare citation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| bare under | 1 | 0.0/1.0 | 0.0 | 1.0 |
| client attribution | 1 | 0.0/1.0 | 0.0 | 1.0 |
| comparison only | 1 | 1.0/1.0 | 1.0 | 1.0 |
| conditional reliance | 1 | 0.0/1.0 | 0.0 | 1.0 |
| consideration not reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| counterparty attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| court attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| cross sentence adoption | 1 | 1.0/0.0 | 1.0 | 1.0 |
| cross sentence rule anchor | 1 | 1.0/0.0 | 1.0 | 1.0 |
| derivation named artifact | 1 | 1.0/0.0 | 1.0 | 1.0 |
| derives from | 1 | 1.0/0.0 | 1.0 | 1.0 |
| direct depends on | 1 | 1.0/1.0 | 1.0 | 1.0 |
| direct relies on | 1 | 1.0/0.0 | 1.0 | 1.0 |
| direct required by after actor | 1 | 1.0/1.0 | 1.0 | 1.0 |
| follows for | 1 | 1.0/0.0 | 1.0 | 1.0 |
| grounded in | 1 | 1.0/0.0 | 1.0 | 1.0 |
| having regard to | 1 | 1.0/0.0 | 1.0 | 1.0 |
| heading only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| historical only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| hypothetical | 1 | 1.0/1.0 | 1.0 | 0.0 |
| incomplete proposition | 1 | 0.0/1.0 | 0.0 | 1.0 |
| independent assessment | 1 | 1.0/1.0 | 1.0 | 0.0 |
| independent conclusion | 1 | 1.0/1.0 | 1.0 | 0.0 |
| multiple authorities unbound | 1 | 1.0/1.0 | 1.0 | 1.0 |
| negated reliance | 1 | 1.0/1.0 | 1.0 | 0.0 |
| no longer relies | 1 | 0.0/1.0 | 0.0 | 1.0 |
| opponent attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| potential reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| prior document reference | 1 | 1.0/1.0 | 1.0 | 0.0 |
| pursuant to | 1 | 1.0/1.0 | 1.0 | 1.0 |
| pursuant to operational | 1 | 1.0/1.0 | 1.0 | 1.0 |
| qualified follows | 1 | 1.0/0.0 | 1.0 | 1.0 |
| quotation without adoption | 1 | 1.0/1.0 | 1.0 | 0.0 |
| quoted report | 1 | 0.0/1.0 | 0.0 | 1.0 |
| rather than negation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| reference heading | 1 | 1.0/1.0 | 1.0 | 1.0 |
| reference only | 1 | 1.0/1.0 | 1.0 | 1.0 |
| regulator attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| rejected approach | 1 | 1.0/1.0 | 1.0 | 1.0 |
| replacement historical only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| replacement selected authority | 1 | 1.0/0.0 | 1.0 | 1.0 |
| reported position | 1 | 1.0/1.0 | 1.0 | 1.0 |
| reported prior draft | 1 | 1.0/1.0 | 1.0 | 1.0 |
| required by | 1 | 1.0/1.0 | 1.0 | 1.0 |
| scope missing | 1 | 1.0/1.0 | 1.0 | 1.0 |
| section symbol equivalence | 1 | 1.0/1.0 | 1.0 | 1.0 |
| subject to | 1 | 1.0/0.0 | 1.0 | 1.0 |
| subject to named advice | 1 | 1.0/0.0 | 1.0 | 1.0 |
| table reference | 1 | 1.0/1.0 | 1.0 | 0.0 |
| training extract | 1 | 1.0/1.0 | 1.0 | 1.0 |
| treats controlling | 1 | 1.0/0.0 | 1.0 | 1.0 |
| truncated authority | 1 | 1.0/1.0 | 1.0 | 0.0 |
| under with conclusion | 1 | 1.0/1.0 | 1.0 | 1.0 |
| unregistered authority | 1 | 1.0/1.0 | 1.0 | 0.0 |
| unresolved instruction | 1 | 0.0/1.0 | 0.0 | 1.0 |
| upper case equivalence | 1 | 1.0/0.0 | 1.0 | 1.0 |
| uses as rule | 1 | 1.0/0.0 | 1.0 | 1.0 |
| witness attribution | 1 | 1.0/1.0 | 1.0 | 0.0 |
| wrapped whitespace equivalence | 1 | 1.0/0.0 | 1.0 | 1.0 |

## Error-stage distribution

| Stage | Count |
| --- | ---: |
| mention mistaken for reliance | 7 |
| reference not detected | 5 |
| reliance cue not recognized | 16 |
