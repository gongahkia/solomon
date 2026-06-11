<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0004: Kaypoh as the Boundary

## Status

Accepted.

## Context

Kaypoh already implements the sanitising boundary Solomon needs: `/review`, `/pseudonymize`,
`/reidentify`, document scrub, strict jurisdiction profiles, and a local/server SKU model. Solomon's value
is the currency layer, not another privacy gateway.

## Decision

Solomon reuses Kaypoh as an external sibling dependency and does not fork or edit Kaypoh source.

| Concern | Solomon behavior |
|---|---|
| Ingestion safety gate | Call Kaypoh `/review` before storage. |
| Outbound model context | Call Kaypoh `/pseudonymize`; retain mapping only in volatile memory. |
| Inbound model response | Call Kaypoh `/reidentify`; flush the volatile mapping after use. |
| Document file ingestion | Call Kaypoh `/documents/scrub` before extraction. |
| Kaypoh unavailable | Fail closed. |

## Consequences

Solomon's CI includes a Kaypoh-local smoke job. Unit tests may use fakes, but product code keeps Kaypoh as
the boundary contract.

