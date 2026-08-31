<!-- SPDX-License-Identifier: Apache-2.0 -->

# Adversarial Dependency Generalization Challenge Corpus Card

## Purpose

This corpus measures deterministic citation/reference and dependency-suggestion behavior under synthetic adversarial
constructions. It is not firm data, legal advice, a legal benchmark, or a substitute for curator or lawyer review.
It deliberately includes items where abstention is the desired result.

## Composition and provenance

Version `1.0.0` contains 84 independently authored fictional documents: 32 development and 52 locked holdout.
It contains 35 affirmative dependency labels, 32 hard-negative labels, and 17 ambiguous/abstention labels. The
fixtures were written from the protocol’s semantic categories before challenge evaluation; they do not copy, mutate,
or mechanically extend the earlier 23-fixture Evidence-to-Dependency corpus.

Every item supplies tenant/matter/client scope where applicable, candidate authority identifiers, exact source-text
reference/evidence spans, a target or abstention label, semantic category, rationale, expected suggestion count, and
whether a human could later confirm an edge. The loader derives offsets from the declared exact source substring and
validates them without invoking Solomon’s extractor. Duplicate text uses an explicit occurrence ordinal.

## Coverage

The base corpus spans full and abbreviated authorities, sections/subsections, case strings, citations before and after
propositions, cross-sentence and cross-paragraph relationships, parentheticals, line breaks, Unicode punctuation,
bounded OCR-like spacing, similar names, unknown targets, quotations, attribution, negation, criticism,
hypotheticals, reading lists, tables, metadata, instruction-like text, internal-policy citations, ambiguous forms,
tenant/matter/client boundaries, duplicate ingestion, rejected/deferred states, revisions, and reordered source text.

The fixed mutation manifest is reported separately from base metrics. Its 12 variants cover whitespace, wrapping,
quote, punctuation, heading, footnote, case, section-symbol, parenthetical, paragraph-boundary, and declared-alias
changes. A mutation is included only when its accompanying rationale states why it preserves label semantics.

## Governance and limits

The holdout becomes immutable at the challenge-lock commit. An objectively defective fixture requires a recorded
defect, corpus version/hash increment, and comparability note; it must never be silently changed to match extractor
output. A perfect score on this corpus would still not establish legal correctness, external generalization, citation
coverage, user understanding, law-firm readiness, or confidentiality compliance.
