# Adversarial Dependency Challenge Evaluation

Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.

- corpus version: `1.0.0`
- manifest SHA-256: `bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256`
- split: `holdout` (52 base fixtures)
- runtime: `188.607` ms
- repeat-run determinism: `True`

## Aggregate metrics

| Metric | Value | Raw count |
| --- | ---: | ---: |
| reference precision | 0.924528 | 49/53 |
| reference recall | 0.942308 | 49/52 |
| target resolution precision | 0.924528 | 49/53 |
| target resolution recall | 0.942308 | 49/52 |
| suggestion precision | 1.0 | 16/16 |
| suggestion recall | 0.8 | 16/20 |
| exact evidence span accuracy | 0.8 | 16/20 |
| overlap or containment span accuracy | 0.8 | 16/20 |
| abstention accuracy | 1.0 | 34/34 |
| hard negative false positive rate | 0.0 | 0/20 |
| duplicate suggestion rate | 0.0 | 0/16 |
| suggestions per 100 items | 30.769231 | 1600/52 |
| false positive suggestions per 100 items | 0.0 | 0/52 |
| cross scope leakage count | 0.0 | 0/1 |
| pre review confirmed edge count | 0.0 | 0/1 |

## Per-category results

| Category | Items | Suggestion P/R | Abstention | FP rate |
| --- | ---: | --- | ---: | ---: |
| alias variation | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous cross reference | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous document name | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous internal dependency | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous malformed | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous multi authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous ocr | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous pronoun | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous quote attribution | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous scope | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous short form | 2 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous version | 1 | 1.0/1.0 | 1.0 | 1.0 |
| attributed other party | 2 | 1.0/1.0 | 1.0 | 0.0 |
| authority as organization | 1 | 1.0/1.0 | 1.0 | 0.0 |
| background only | 2 | 1.0/1.0 | 1.0 | 0.0 |
| citation before reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| cross paragraph reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| cross sentence reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| deferred evidence | 1 | 1.0/1.0 | 1.0 | 1.0 |
| distinguishing or criticism | 1 | 1.0/1.0 | 1.0 | 0.0 |
| duplicate citation no dependency | 1 | 1.0/1.0 | 1.0 | 0.0 |
| explicit reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| footnote like reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| historical reliance replaced | 1 | 1.0/1.0 | 1.0 | 0.0 |
| hypothetical | 1 | 1.0/1.0 | 1.0 | 0.0 |
| instruction like text | 1 | 1.0/1.0 | 1.0 | 0.0 |
| internal policy citation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| multiple authorities | 2 | 1.0/1.0 | 1.0 | 1.0 |
| negation | 1 | 1.0/1.0 | 1.0 | 0.0 |
| parenthetical provision | 1 | 1.0/0.0 | 1.0 | 1.0 |
| qualified reliance | 1 | 1.0/0.0 | 1.0 | 1.0 |
| quotation without adoption | 1 | 1.0/1.0 | 1.0 | 0.0 |
| reliance without legacy cue | 2 | 1.0/0.5 | 1.0 | 1.0 |
| reordered semantically unchanged | 1 | 1.0/1.0 | 1.0 | 1.0 |
| revision changes provision | 1 | 1.0/1.0 | 1.0 | 1.0 |
| same document different scope | 1 | 1.0/1.0 | 1.0 | 1.0 |
| same sentence no relationship | 1 | 1.0/1.0 | 1.0 | 0.0 |
| scope lifecycle | 3 | 1.0/0.5 | 1.0 | 0.0 |
| search metadata | 1 | 1.0/1.0 | 1.0 | 0.0 |
| similar authority names | 1 | 1.0/1.0 | 1.0 | 0.0 |
| superseded draft language | 1 | 1.0/1.0 | 1.0 | 0.0 |
| table of authorities | 1 | 1.0/1.0 | 1.0 | 0.0 |
| unknown authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| versioned authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| wrong authority near cue | 1 | 1.0/1.0 | 1.0 | 0.0 |

## Error-stage distribution

| Stage | Count |
| --- | ---: |
| reference not detected | 3 |
| reliance cue not recognized | 4 |
