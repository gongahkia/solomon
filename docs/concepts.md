<!-- SPDX-License-Identifier: Apache-2.0 -->

# Concepts

## Currency vs Significance

Shibahama-style decay asks whether a memory still matters. Solomon asks whether a legal position still
holds. Old is not stale; stale means a dependency moved, verification expired, or a successor closed the
validity window.

## Bi-Temporality

`valid_from` and `valid_to` describe when an item is legally or operationally valid. `ingested_at` describes
when the firm learned or stored it. Both matter for "what did we know and when" questions.

## Dependency Graph

Internal knowledge can depend on external authorities or other internal items. When a dependency changes,
Solomon flags transitive dependents as `StalePendingReverification`.

## Credence

Source matters. Partner-signed content starts above model-generated content. Low-credence items can be
retrieved for review but cannot be presented as settled load-bearing output.

## Verification

Verification refreshes `last_verified_at`, records `verified_by`, and can reaffirm, retire, or supersede an
item. Supersession is human-confirmed.

