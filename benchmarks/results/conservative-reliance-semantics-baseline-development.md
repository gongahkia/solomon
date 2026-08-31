# Conservative Reliance Semantics Evaluation

Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.

- corpus version: `1.0.0`
- manifest SHA-256: `3e2757e6fe7e47e0c5af0629db16fa9c42f596a292079a7f0e33efaebb1d6820`
- split: `development` (24 base fixtures)
- runtime: `298.708` ms
- repeat-run determinism: `True`

## Aggregate metrics

| Metric | Value | Raw count |
| --- | ---: | ---: |
| reference precision | 0.923077 | 24/26 |
| reference recall | 0.96 | 24/25 |
| target resolution precision | 0.923077 | 24/26 |
| target resolution recall | 0.96 | 24/25 |
| suggestion precision | 0.571429 | 4/7 |
| suggestion recall | 0.444444 | 4/9 |
| exact evidence span accuracy | 0.444444 | 4/9 |
| overlap or containment span accuracy | 0.444444 | 4/9 |
| abstention accuracy | 0.8 | 12/15 |
| hard negative false positive rate | 0.125 | 1/8 |
| duplicate suggestion rate | 0.0 | 0/7 |
| suggestions per 100 items | 29.166667 | 700/24 |
| false positive suggestions per 100 items | 12.5 | 300/24 |
| cross scope leakage count | 0.0 | 0/1 |
| pre review confirmed edge count | 0.0 | 0/1 |

## Per-category results

| Category | Items | Suggestion P/R | Abstention | FP rate |
| --- | ---: | --- | ---: | ---: |
| adoption local | 1 | 1.0/0.0 | 1.0 | 1.0 |
| alternative authorities | 1 | 1.0/1.0 | 1.0 | 1.0 |
| background table | 1 | 1.0/1.0 | 1.0 | 0.0 |
| bare citation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| client attribution | 1 | 0.0/1.0 | 0.0 | 1.0 |
| comparison only | 1 | 1.0/1.0 | 1.0 | 1.0 |
| derives from | 1 | 1.0/0.0 | 1.0 | 1.0 |
| direct depends on | 1 | 1.0/1.0 | 1.0 | 1.0 |
| direct relies on | 1 | 1.0/0.0 | 1.0 | 1.0 |
| grounded in | 1 | 1.0/0.0 | 1.0 | 1.0 |
| historical only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| hypothetical | 1 | 1.0/1.0 | 1.0 | 0.0 |
| incomplete proposition | 1 | 0.0/1.0 | 0.0 | 1.0 |
| independent conclusion | 1 | 1.0/1.0 | 1.0 | 0.0 |
| negated reliance | 1 | 1.0/1.0 | 1.0 | 0.0 |
| pursuant to | 1 | 1.0/1.0 | 1.0 | 1.0 |
| quotation without adoption | 1 | 1.0/1.0 | 1.0 | 0.0 |
| reference only | 1 | 1.0/1.0 | 1.0 | 1.0 |
| reported position | 1 | 1.0/1.0 | 1.0 | 1.0 |
| required by | 1 | 1.0/1.0 | 1.0 | 1.0 |
| scope missing | 1 | 1.0/1.0 | 1.0 | 1.0 |
| subject to | 1 | 1.0/0.0 | 1.0 | 1.0 |
| under with conclusion | 1 | 1.0/1.0 | 1.0 | 1.0 |
| unresolved instruction | 1 | 0.0/1.0 | 0.0 | 1.0 |

## Error-stage distribution

| Stage | Count |
| --- | ---: |
| mention mistaken for reliance | 3 |
| reference not detected | 1 |
| reliance cue not recognized | 5 |
