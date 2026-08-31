# Adversarial Dependency Challenge Evaluation

Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.

- corpus version: `1.0.0`
- manifest SHA-256: `bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256`
- split: `all` (84 base fixtures)
- runtime: `218.487` ms
- repeat-run determinism: `True`

## Aggregate metrics

| Metric | Value | Raw count |
| --- | ---: | ---: |
| reference precision | 0.843373 | 70/83 |
| reference recall | 0.804598 | 70/87 |
| target resolution precision | 0.86747 | 72/83 |
| target resolution recall | 0.827586 | 72/87 |
| suggestion precision | 0.730769 | 19/26 |
| suggestion recall | 0.5 | 19/38 |
| exact evidence span accuracy | 0.447368 | 17/38 |
| overlap or containment span accuracy | 0.447368 | 17/38 |
| abstention accuracy | 0.938776 | 46/49 |
| hard negative false positive rate | 0.09375 | 3/32 |
| duplicate suggestion rate | 0.0 | 0/26 |
| suggestions per 100 items | 30.952381 | 2600/84 |
| false positive suggestions per 100 items | 8.333333 | 700/84 |
| cross scope leakage count | 0.0 | 0/1 |
| pre review confirmed edge count | 0.0 | 0/1 |

## Per-category results

| Category | Items | Suggestion P/R | Abstention | FP rate |
| --- | ---: | --- | ---: | ---: |
| acronym alias | 1 | 1.0/0.0 | 1.0 | 1.0 |
| alias variation | 1 | 1.0/1.0 | 1.0 | 1.0 |
| alternative independent grounds | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous cross reference | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous document name | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous internal dependency | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous malformed | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous multi authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous ocr | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous pronoun | 2 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous quote attribution | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous scope | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous short form | 3 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous version | 1 | 1.0/1.0 | 1.0 | 1.0 |
| attributed other party | 3 | 0.0/1.0 | 0.0 | 1.0 |
| authority as organization | 2 | 1.0/1.0 | 1.0 | 0.0 |
| background only | 3 | 1.0/1.0 | 1.0 | 0.0 |
| bibliography | 1 | 1.0/1.0 | 1.0 | 0.0 |
| case reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| citation after proposition | 1 | 1.0/0.0 | 1.0 | 1.0 |
| citation before reliance | 1 | 0.0/0.0 | 1.0 | 1.0 |
| cross paragraph reliance | 1 | 1.0/0.0 | 1.0 | 1.0 |
| cross sentence reliance | 2 | 1.0/0.0 | 1.0 | 1.0 |
| deferred evidence | 1 | 1.0/1.0 | 1.0 | 1.0 |
| distinguishing or criticism | 2 | 1.0/1.0 | 1.0 | 0.0 |
| duplicate citation no dependency | 1 | 1.0/1.0 | 1.0 | 0.0 |
| duplicate citation one dependency | 1 | 1.0/1.0 | 1.0 | 1.0 |
| explicit reliance | 2 | 1.0/1.0 | 1.0 | 1.0 |
| footnote like reliance | 2 | 1.0/0.5 | 1.0 | 1.0 |
| historical reliance replaced | 1 | 1.0/1.0 | 1.0 | 0.0 |
| hypothetical | 2 | 1.0/1.0 | 1.0 | 0.0 |
| instruction like text | 2 | 1.0/1.0 | 1.0 | 0.0 |
| internal policy citation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| line break citation | 1 | 1.0/1.0 | 1.0 | 1.0 |
| matter limited reliance | 1 | 1.0/0.0 | 1.0 | 1.0 |
| multiple authorities | 2 | 0.666667/0.5 | 1.0 | 1.0 |
| negation | 3 | 1.0/1.0 | 1.0 | 0.0 |
| ocr like noise | 1 | 1.0/1.0 | 1.0 | 1.0 |
| parenthetical provision | 1 | 0.0/0.0 | 1.0 | 1.0 |
| partial reliance | 1 | 0.0/0.0 | 1.0 | 1.0 |
| qualified reliance | 2 | 1.0/0.5 | 1.0 | 1.0 |
| quotation without adoption | 2 | 1.0/1.0 | 1.0 | 0.0 |
| reliance without legacy cue | 3 | 1.0/0.0 | 1.0 | 1.0 |
| reordered semantically unchanged | 1 | 1.0/1.0 | 1.0 | 1.0 |
| revision changes provision | 1 | 1.0/1.0 | 1.0 | 1.0 |
| revision introduces reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| revision removes reliance | 1 | 1.0/1.0 | 1.0 | 0.0 |
| same document different scope | 2 | 1.0/0.0 | 1.0 | 1.0 |
| same sentence no relationship | 1 | 1.0/1.0 | 1.0 | 0.0 |
| scope lifecycle | 3 | 1.0/0.5 | 1.0 | 0.0 |
| search metadata | 1 | 1.0/1.0 | 1.0 | 0.0 |
| similar authority names | 1 | 1.0/1.0 | 1.0 | 0.0 |
| smart punctuation | 1 | 1.0/1.0 | 1.0 | 1.0 |
| superseded draft language | 1 | 1.0/1.0 | 1.0 | 0.0 |
| table of authorities | 1 | 1.0/1.0 | 1.0 | 0.0 |
| unknown authority | 2 | 1.0/1.0 | 1.0 | 1.0 |
| versioned authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| wrong authority near cue | 2 | 1.0/1.0 | 1.0 | 0.0 |

## Error-stage distribution

| Stage | Count |
| --- | ---: |
| cross sentence relationship missed | 3 |
| evidence span over broad | 2 |
| mention mistaken for reliance | 4 |
| quoted or attributed position mistaken for firm reliance | 3 |
| reference not detected | 27 |
| reliance cue not recognized | 6 |
