<!-- SPDX-License-Identifier: Apache-2.0 -->

# Why Solomon

Solomon exists because law-firm knowledge has a different failure mode from ordinary memory systems.

Most memory tools ask what should be remembered. Legal knowledge systems also ask what can be reused.
Solomon asks a narrower, sharper question: what did the firm believe, what did that belief depend on, and
does a human need to re-check it because something moved?

## The Triad

| System | Center of gravity | What it proves |
|---|---|---|
| Kaypoh | Boundary control | Sensitive text can be reviewed, pseudonymized, and reidentified without persistent mappings. |
| Shibahama | Memory selection | Some facts should fade or lose rank when they stop being useful. |
| Solomon | Knowledge currency | Internal legal knowledge can be permanent, bi-temporal, dependency-aware, and still safe to use. |

Kaypoh is the front gate. Shibahama is the memory-pressure argument. Solomon is the audit and currency layer
for a professional knowledge base where old does not mean wrong.

## Why Decay Is The Wrong Primitive

Decay is attractive in generic memory systems because recency often predicts usefulness. In law-firm knowledge,
recency is not the same as validity:

- A ten-year-old signed partner view may still be the firm position.
- A two-week-old model summary may be low credence and unsafe for load-bearing output.
- A 2023 memo may become stale in 2025 because the regulation it depends on changed.
- A 2024 memo may supersede a 2022 memo even if both are textually similar.

The core primitive is therefore not age. It is dependency movement plus verification.

## The Wedge

Every firm checks whether a case is still good law. Very few systems check whether the firm's own internal
knowledge is still good law. Solomon turns that into a product surface:

- default recall hides stale and superseded items;
- review-mode recall preserves them with labels and reasons;
- `why(item)` shows provenance, dependency edges, supersession, credence, and verification state;
- `timeline(query, as_of)` reconstructs what the firm knew at a past point in time;
- the audit journal records metadata and hashes so the firm can defend the process without leaking content.

## Product Judgment

Solomon deliberately flags, rather than adjudicates. It does not say a position is legally wrong. It says the
dependency graph, supersession chain, or verification policy shows that a human should re-check the item before
the firm relies on it again.

That is the defensible automation boundary: the system preserves memory, finds currency breaks, and explains
why review is due. The lawyer decides the law.
