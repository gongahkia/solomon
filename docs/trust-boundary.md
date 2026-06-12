<!-- SPDX-License-Identifier: Apache-2.0 -->

# Trust Boundary

Solomon fails closed at ingest and model egress. Knowledge items must pass the vendored Kaypoh-derived
`/review` surface before storage. Model context must pass the vendored `/pseudonymize`; the mapping remains
only in process memory and is flushed after `/reidentify`. `raw_text` mode is disabled by default and requires
a per-matter opt-in.

Stored knowledge is also untrusted input. Retrieval code treats knowledge as data, not instructions:
instruction-role items are excluded from prompt context, stale items are not returned by default, and
low-credence items cannot be presented as settled.
