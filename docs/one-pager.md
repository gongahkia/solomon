<!-- SPDX-License-Identifier: Apache-2.0 -->

# Solomon: currency infrastructure for verified legal knowledge

## The problem

Firm knowledge is reusable only while its authority, verification, and internal status remain current. Search can
find a useful memo but cannot by itself show whether an upstream authority moved, a later firm view superseded it, or
a lawyer contested it.

## The product

Solomon is an MCP-native layer that records provenance, valid and ingestion time, dependencies, verification,
supersession, contestability, and metadata-only audit evidence. It returns live positions by default and marks
dependent positions stale-pending-reverification when a recorded authority change requires review.

## How it fits

An MCP host calls `preflight_context` before prompt assembly, then calls `why`, `impact`, or `audit_pack` when
review is required. Solomon is compatible with a DMS, knowledge search system, or legal AI host; it does not replace
those systems, monitor every authority, or decide legal correctness.

## Evidence path

1. Ingest knowledge through boundary review.
2. Record or confirm dependencies.
3. Register a relevant authority or internal-position change.
4. Propagate a review state to affected positions.
5. Reaffirm, supersede, retire, or contest with evidence.
6. Export a metadata-only, hash-verified audit pack.

## Controls and limits

- Dependency movement, not age alone, drives currency.
- Boundary failures fail closed for ingestion and model egress.
- A lawyer retains responsibility for verification, legal judgement, and final work product.
- Deployment, retention, confidentiality, and regulatory obligations remain firm-owned.

## Review checklist

Ask: What is current? What changed? Which matters are affected? Who verified the position? What evidence supports the
answer? Solomon stores the evidence required to answer those questions reproducibly.

See the [README](https://github.com/gongahkia/solomon), [positioning](./positioning.md), and
[known limitations](./known-limitations.md).
