<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0003: Flag, Do Not Adjudicate

## Status

Accepted.

## Context

Solomon observes that a dependency moved or a verification age threshold expired. It cannot decide whether
the underlying legal position is wrong without human legal judgment.

## Decision

Solomon flags items as stale-pending-reverification and records why. It never asserts that a legal position
is broken, invalid, or overruled. User-facing output must preserve the distinction between "dependency
moved" and "position is wrong."

## Consequences

APIs return explanations and evidence chains, not legal conclusions. The product is conservative by
construction and supports human review rather than replacing it.

