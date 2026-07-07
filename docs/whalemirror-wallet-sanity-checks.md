# WhaleMirror Wallet Sanity Checks (#15)

Status: checked on 2026-07-07.

This document is a validation note, not a profitability claim. It combines the reproducible fixture ranking with public-source checks for the top activity wallets from the May 2026 shortlist.

## Reproducible Ranking Output

Command:

```sh
PYTHONPATH=src python3 -m stonks_cli whalemirror wallets rank \
  --fixture tests/fixtures/whalemirror/wallet-attribution.jsonl \
  --limit 100 \
  --markdown
```

The current fixture contains 3 ranked wallets, not 100. Top-100 coverage cannot be claimed until a larger closed-outcome dataset is committed.

| Rank | Wallet | Fixture Result | Public Source Check |
| ---: | --- | --- | --- |
| 1 | `0xaaa0000000000000000000000000000000000001` | Sample size 3, funding included, small-sample caveat. | No indexed Hyperdash/Hyperliquid profile found in web search; fixture-style address likely synthetic. |
| 2 | `0xbbb0000000000000000000000000000000000002` | Sample size 1, high-leverage 20x caveat. | No indexed Hyperdash/Hyperliquid profile found in web search; fixture-style address likely synthetic. |
| 3 | `0xccc0000000000000000000000000000000000003` | Sample size 2, funding included, negative fixture expectancy. | No indexed Hyperdash/Hyperliquid profile found in web search; fixture-style address likely synthetic. |

## Public Sources Checked

- [Hyperliquid leaderboard](https://app.hyperliquid.xyz/leaderboard)
- [Hyperdash global traders](https://hyperdash.com/explore/global)
- [Hyperliquid public info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), using `userFillsByTime`

Web search found Hyperdash and Hyperliquid leaderboard surfaces, but did not return indexed address-specific public profile pages for the wallets below. Continued activity was checked through the public Hyperliquid info endpoint.

## Top-10 Activity Wallet Checks

Top-10 is selected from [May 2026 wallet activity shortlist](whalemirror-wallet-activity-shortlist-2026-05.md), not from profitability attribution.

| Rank | Wallet | Public Profile | 7-Day Public Fill Check | Classification | Caveats | Verdict |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `0x2ca4927174ba283d8a57f60ef3589844035a2930` | No indexed address profile found; Hyperdash/global and Hyperliquid leaderboard remain manual search surfaces. | 2,000 fills, cap hit, 2026-07-06T17:39:01Z to 2026-07-06T18:04:08Z. | unclear high-frequency flow | survivorship, funding unknown, leverage unknown, sample cap, stale local capture | reject live target; allow paper-observation only |
| 2 | `0x55f389689b39fdd29d063f8b1aa776666a2dd788` | No indexed address profile found. | 0 fills in 7-day query. | stale/unclear | stale data, no recent fills, survivorship, funding unknown, leverage unknown | reject |
| 3 | `0xf5d81a135f756ca16544e53c20fc20643ec3ad53` | No indexed address profile found. | 2,000 fills, cap hit, 2026-07-06T23:15:31Z to 2026-07-06T23:41:05Z. | unclear high-frequency flow | sample cap, market-making/liquidation risk, funding unknown, leverage unknown | paper-observation candidate only |
| 4 | `0xabfae5ef417fec83a63dcdbff5a13f71d09045c5` | No indexed address profile found. | May enrichment hit 2,000-fill cap; not re-queried in 7-day batch. | unclear | stale data, sample cap, funding unknown, leverage unknown | reject until refreshed |
| 5 | `0xd4c1f7e8d876c4749228d515473d36f919583d1d` | No indexed address profile found. | May enrichment hit 2,000-fill cap; not re-queried in 7-day batch. | unclear | stale data, sample cap, funding unknown, leverage unknown | reject until refreshed |
| 6 | `0xf4b8a39b7b828d8e059a55ed697a3dec634b6488` | No indexed address profile found. | 2,000 fills, cap hit, 2026-06-30T02:21:09Z to 2026-06-30T13:00:55Z. | unclear high-frequency flow | sample cap, stale since 2026-06-30 in 7-day query, funding unknown, leverage unknown | paper-observation candidate only |
| 7 | `0xd02928c445d780ea954fe0b6f0be0f6cb9727678` | No indexed address profile found. | 0 fills in 7-day query. | stale/unclear | stale data, survivorship, funding unknown, leverage unknown | reject |
| 8 | `0x348e5365acfa48a26ada7da840ca611e29c950ef` | No indexed address profile found. | 0 fills in 7-day query. | stale/unclear | stale data, survivorship, funding unknown, leverage unknown | reject |
| 9 | `0x31dea2516beee92135b96f464eeec3cf292a13f2` | No indexed address profile found. | May enrichment hit 2,000-fill cap; not re-queried in 7-day batch. | unclear | stale data, sample cap, funding unknown, leverage unknown | reject until refreshed |
| 10 | `0x5a7581618829f377a16be2338eabdd03fece0eaf` | No indexed address profile found. | May enrichment hit 2,000-fill cap; not re-queried in 7-day batch. | unclear | stale data, sample cap, funding unknown, leverage unknown | reject until refreshed |

## Required Caveats

- Survivorship: high activity screens can overrepresent wallets that survived the local capture window.
- Leverage: complete leverage history is not available in the activity shortlist.
- Funding: full wallet-level funding cost is not available for the top-10 activity wallets.
- Sample size: fixture ranking has only 3 wallets; activity enrichment can cap at 2,000 fills.
- Stale data: May 2026 local capture is stale as of 2026-07-07 unless refreshed by public API checks.
- Behavior ambiguity: high activity can be market-making, liquidation flow, or passive flow, not directional skill.

## Product Constraint

No marketing copy may claim unsupported alpha from these rankings. Wallet data can feed research and paper-observation queues only; it cannot feed live target selection.
