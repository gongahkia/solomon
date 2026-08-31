<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0001: Reject Decay for Legal Currency

## Status

Accepted.

## Context

Significance decay is a reasonable fit for knowledge whose value fades with neglect. Law-firm knowledge has a
different failure mode: an old position can remain controlling for years, and a fresh position can become stale
immediately if its dependency moves.

## Decision

Solomon will not use age or usage decay to decide legal currency. Currency is dependency-driven:

- what the item relies on,
- whether those dependencies moved,
- whether the item itself was superseded or retired,
- and whether verification is overdue under firm policy.

## Consequences

Solomon must store dependencies explicitly and preserve old items. An item being old is never enough to
downgrade it; an item being new is never enough to trust it.
