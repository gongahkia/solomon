# Adversarial Dependency Challenge Evaluation

Synthetic engineering evidence only. No prediction is automatically trusted, confirmed, or propagated.

- corpus version: `1.0.0`
- manifest SHA-256: `bf391fb28a7a76f595aa6399d578bc699c38c3e0745014fd63053ed6a7bf4256`
- split: `development` (32 base fixtures)
- runtime: `174.099` ms
- repeat-run determinism: `True`

## Aggregate metrics

| Metric | Value | Raw count |
| --- | ---: | ---: |
| reference precision | 0.916667 | 33/36 |
| reference recall | 0.942857 | 33/35 |
| target resolution precision | 0.916667 | 33/36 |
| target resolution recall | 0.942857 | 33/35 |
| suggestion precision | 1.0 | 17/17 |
| suggestion recall | 0.944444 | 17/18 |
| exact evidence span accuracy | 0.944444 | 17/18 |
| overlap or containment span accuracy | 0.944444 | 17/18 |
| abstention accuracy | 1.0 | 15/15 |
| hard negative false positive rate | 0.0 | 0/12 |
| duplicate suggestion rate | 0.0 | 0/17 |
| suggestions per 100 items | 53.125 | 1700/32 |
| false positive suggestions per 100 items | 0.0 | 0/32 |
| cross scope leakage count | 0.0 | 0/1 |
| pre review confirmed edge count | 0.0 | 0/1 |

## Per-category results

| Category | Items | Suggestion P/R | Abstention | FP rate |
| --- | ---: | --- | ---: | ---: |
| acronym alias | 1 | 1.0/1.0 | 1.0 | 1.0 |
| alternative independent grounds | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous pronoun | 1 | 1.0/1.0 | 1.0 | 1.0 |
| ambiguous short form | 1 | 1.0/1.0 | 1.0 | 1.0 |
| attributed other party | 1 | 1.0/1.0 | 1.0 | 0.0 |
| authority as organization | 1 | 1.0/1.0 | 1.0 | 0.0 |
| background only | 1 | 1.0/1.0 | 1.0 | 0.0 |
| bibliography | 1 | 1.0/1.0 | 1.0 | 0.0 |
| case reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| citation after proposition | 1 | 1.0/1.0 | 1.0 | 1.0 |
| cross sentence reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| distinguishing or criticism | 1 | 1.0/1.0 | 1.0 | 0.0 |
| duplicate citation one dependency | 1 | 1.0/1.0 | 1.0 | 1.0 |
| explicit reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| footnote like reliance | 1 | 1.0/0.0 | 1.0 | 1.0 |
| hypothetical | 1 | 1.0/1.0 | 1.0 | 0.0 |
| instruction like text | 1 | 1.0/1.0 | 1.0 | 0.0 |
| line break citation | 1 | 1.0/1.0 | 1.0 | 1.0 |
| matter limited reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| negation | 2 | 1.0/1.0 | 1.0 | 0.0 |
| ocr like noise | 1 | 1.0/1.0 | 1.0 | 1.0 |
| partial reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| qualified reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| quotation without adoption | 1 | 1.0/1.0 | 1.0 | 0.0 |
| reliance without legacy cue | 1 | 1.0/1.0 | 1.0 | 1.0 |
| revision introduces reliance | 1 | 1.0/1.0 | 1.0 | 1.0 |
| revision removes reliance | 1 | 1.0/1.0 | 1.0 | 0.0 |
| same document different scope | 1 | 1.0/1.0 | 1.0 | 1.0 |
| smart punctuation | 1 | 1.0/1.0 | 1.0 | 1.0 |
| unknown authority | 1 | 1.0/1.0 | 1.0 | 1.0 |
| wrong authority near cue | 1 | 1.0/1.0 | 1.0 | 0.0 |

## Error-stage distribution

| Stage | Count |
| --- | ---: |
| reference not detected | 2 |
| reliance cue not recognized | 1 |
