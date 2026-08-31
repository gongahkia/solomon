<!-- SPDX-License-Identifier: Apache-2.0 -->

# Conservative Reliance Semantics: Reversible Mapping Record

This record describes the sole experimental implementation at `65a5853`. That source commit was rejected by the
predeclared locked-holdout gate and reverted by `6164c9e`; it is not the current parser.

## Canonical representation evaluated

`NormalizedAnalysis` held one normalized display string plus one monotone `RawInterval` for every analysis character.
The case-folded string was a matching projection of that view, not a second evidence source. The experimental
normalizer applied NFKC character-by-character, mapped curly single/double quotes to ASCII, expanded `§` to
`section`, and collapsed a contiguous whitespace run (including a safe line wrap) to one analysis space. It preserved
token order, punctuation, sentence separation, names, negation, attribution, and the original raw text.

The mapping policy was deterministic:

| Analysis transformation | Raw mapping retained |
| --- | --- |
| NFKC character expansion | every emitted character maps to its one originating raw character interval |
| Curly quote to ASCII quote | emitted quote maps to its original raw quote character |
| `§` to ` section ` | every emitted matching character maps to the raw `§` interval |
| whitespace run to one space | the analysis space maps to the full original raw whitespace run |
| case-fold matcher projection | no raw mapping changes |

For a matched analysis window, the implementation returned the minimal enclosing raw interval and trimmed only raw
leading/trailing whitespace. Reviewers therefore saw exact original characters—including uppercase text, line breaks,
smart quotes, and `§`—not normalized renderings. Invalid, empty, non-monotone, or out-of-range mappings failed
closed without a candidate.

The associated authority fingerprint was calculated solely from the raw authority slice: NFKC, `§` to `section`,
case-folding, abbreviation expansion for `Reg.`/`s.`, tokenization, and hyphen joining. An optional caller-provided
registered-authority list filtered candidates exactly by this raw-derived fingerprint. No model, embedding, external
authority lookup, automatic edge, confirmation, or propagation mechanism was added.

## Tested mapping invariants

The rejected implementation’s focused test set passed before the holdout run. It covered normalization idempotency;
case/whitespace/quote/section-symbol equivalence; exact raw authority and evidence slicing; invalid map rejection;
local negation, attribution, quotation, and instruction guards; the two-sentence adoption window; registered-target
filtering; deterministic repeated evaluation; existing parser properties; and corpus integrity. The development
evaluation also showed all twelve fixed mutations stable, including the former expanded-whitespace and case-variation
residuals.

These invariant results show that raw-span reversibility itself was implemented as specified. They do not cure the
separate generalization/safety failure on the existing locked 84-fixture corpus, which is why the implementation was
not retained.
