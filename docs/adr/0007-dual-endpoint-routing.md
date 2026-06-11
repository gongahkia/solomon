<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0007: Dual Endpoint Routing

## Status

Accepted.

## Context

Some matters can use a remote ZDR endpoint after Kaypoh sanitisation. Strict matters cannot egress at all,
even with placeholders. Local deployments must work offline by default.

## Decision

Solomon exposes one `ModelEndpoint` interface with remote-ZDR and local implementations. Matter sensitivity
drives routing: strict matters and zero-egress mode force local; standard matters may use remote ZDR only
when egress is explicitly enabled.

## Consequences

Every routing decision emits metadata-only audit fields: endpoint, reason, boundary-crossing flag, prompt
hash, latency, and cost if known. Remote failure may fall back to local only when policy permits and must
carry a quality caveat.

