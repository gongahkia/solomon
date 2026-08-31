<!-- SPDX-License-Identifier: Apache-2.0 -->

# Conservative Reliance Semantics Corpus Card

The locked corpus is a synthetic, fictional engineering fixture set for the one normalized-analysis/grammar
experiment declared in [the proof contract](../roadmap/conservative-reliance-semantics-proof.md). It is not legal
advice, a claim of legal-language coverage, or training data for a model.

`manifest.json` contains 64 independently authored raw-text fixtures: exactly 24 development and 40 locked holdout;
24 affirmative reliance cases; 24 hard negatives; and 16 ambiguous cases. The contents are new authored material with
new fictional authority names and semantic situations; they are not copied, paraphrased, or mechanically transformed
from the prior 84-fixture adversarial dependency corpus.

Each fixture supplies scope, registered candidates, raw reference labels, an exact raw evidence span and target for
an affirmative case, or explicit abstention labels for every other case. The negative and ambiguous coverage includes
third-party and quoted voice, negation, historical/replacement context, hypothetical and conditional language,
background tables and headings, missing registration, multiple authorities, incomplete citations, and instruction or
training text. Affirmative coverage includes direct reliance, direct predicate variants, adoption, a limited
cross-sentence anchor, qualified present reliance, uppercase input, repeated/wrapped whitespace, Unicode quotes, and
the section symbol.

The verifier rejects a hash mismatch, malformed source evidence, labels that do not match the declared count, a
suggestion that is not registered in scope, and a non-affirmative fixture that carries evidence. It does not invoke
extraction, create suggestions, or access persistence.
