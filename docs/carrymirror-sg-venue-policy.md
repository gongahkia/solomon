# CarryMirror SG Venue Policy

Status: accepted for GitHub issue #16.

This is an operational blocklist, not legal advice. Review date: 2026-07-07.

## Product Decision

CarryMirror funding/basis carry is the first live-candidate product path. WhaleMirror copy-trading remains research-only and cannot feed live target selection.

## Source Checks

| Source | Finding | Policy Impact |
| --- | --- | --- |
| [MAS Financial Institutions Directory: Major Payment Institution + Digital Payment Token Service](https://eservices.mas.gov.sg/fid/institution?activity=Digital+Payment+Token+Service&category=Major+Payment+Institution&sector=Payments) | MAS lists DPT-service MPIs, including examples such as Bitstamp Asia, Coinbase Singapore, Circle Internet Singapore, and DBS Vickers. | Spot/fiat rails must be MAS-licensed or separately reviewed before use. |
| [Hyperliquid Terms](https://app.hyperliquid.xyz/terms) | Terms are reviewed separately before live use. | Hyperliquid stays paper-first until paper gate, terms review, custody review, and live preflight pass. |
| [Polymarket Geographic Restrictions](https://help.polymarket.com/en/articles/13364163-geographic-restrictions) | Singapore appears in restricted/close-only geographies; opening new positions is not allowed by platform policy. | Polymarket execution is blocked. |
| [Bybit Service Restricted Countries](https://www.bybit.com/en/help-center/article/Service-Restricted-Countries) | Bybit states it does not offer services/products to users in Singapore. | Bybit execution is blocked until reviewed and removed from the blocklist. |
| [Kalshi Member Agreement](https://kalshi.com/docs/kalshi-member-agreement.pdf) | Kalshi is described as a CFTC-designated contract market, with user obligations to comply with applicable laws. | Kalshi is blocked pending SG legal review; U.S. regulatory status is not treated as SG authorization. |

## Runtime Policy

| Venue Or Strategy | Runtime Status |
| --- | --- |
| Hyperliquid carry scanner | Allowed in paper mode only. |
| Hyperliquid carry paper engine | Allowed. |
| Hyperliquid tiny live | Blocked until paper gate, legal review, custody review, risk preflight, and explicit live arm pass. |
| MAS-licensed spot/fiat rails | Allowed only after specific integration review. |
| Polymarket | Blocked. |
| Kalshi | Blocked. |
| Sportsbooks | Blocked. |
| Bybit | Blocked. |
| Prediction-market strategies | Blocked. |
| Sportsbook/sports-betting strategies | Blocked. |
| WhaleMirror live target selection from wallet rankings | Blocked. |

## Enforcement

- Config defaults: `legal_policy.blocked_venue_ids` blocks `polymarket`, `kalshi`, `sportsbook`, `sportsbooks`, and `bybit`.
- Config defaults: `legal_policy.blocked_strategy_classes` blocks prediction-market, sportsbook, circumvention, and WhaleMirror live-target strategy classes.
- CarryMirror scanner and paper commands call the legal policy before venue-specific execution.
- Live guard checks block SG-restricted venues and strategy classes before arm-flag checks can pass.

## Review Before Live

Before any live CarryMirror path can be armed, record:

- Hyperliquid terms review.
- MAS/DPT rail review.
- Custody and API-key/security review.
- Tax recordkeeping review.
- Venue-specific prohibited-jurisdiction review.
- Signed operator acknowledgement that no blocked venue or strategy class is involved.
