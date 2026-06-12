<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0004: Kaypoh as the Boundary

## Status

Accepted.

## Context

Kaypoh already implements the sanitising boundary Solomon needs: `/review`, `/pseudonymize`,
`/reidentify`, document scrub, strict jurisdiction profiles, and a local/server SKU model. Solomon's value
is the currency layer, not another privacy gateway.

## Decision

Solomon vendors the Kaypoh-derived local boundary surfaces it needs under `src/solomon/boundary/engine/`,
with provenance and source commit recorded in the vendored `NOTICE`. This makes Solomon self-contained while
keeping the origin explicit.

| Concern | Solomon behavior |
|---|---|
| Ingestion safety gate | Call the vendored `/review` surface before storage. |
| Outbound model context | Call the vendored `/pseudonymize`; retain mapping only in volatile memory. |
| Inbound model response | Call the vendored `/reidentify`; flush the volatile mapping after use. |
| Document file ingestion | Call the vendored `/documents/scrub` before extraction. |
| Boundary unavailable | Fail closed. |

## Consequences

Solomon's CI includes a vendored boundary smoke job. Unit tests may still use fakes for edge cases, but the
default service path uses the in-process vendored boundary.
