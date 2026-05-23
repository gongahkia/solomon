# WhaleMirror Wallet Activity Shortlist - May 2026

## Scope

This shortlist is derived from the May 2026 partial capture archive. It is an activity screen, not an alpha or profitability ranking.

The capture contains public Hyperliquid trade observations and normalized buyer/seller rows. It does not contain closed-position outcomes, complete funding, fee, leverage, or drawdown history for every wallet. Use this list to choose candidates for deeper public-source checks, not to select live mirror targets.

Source archive:

```text
~/.local/state/stonks-cli/whalemirror-gates/archive/partial-2026-05-17-to-2026-05-20/
```

## Selection Logic

Candidate signals:

- high normalized row count
- high observed row notional
- continued public `userFillsByTime` activity after the local capture stopped
- multi-market activity where available

Hard caveats:

- normalized public-trade rows include both sides of each trade
- high activity can be market making, liquidation flow, or passive flow, not necessarily directional skill
- public fill enrichment hit Hyperliquid's 2,000-row response cap for every queried top-activity wallet
- no wallet below should be treated as profitable without closed-outcome attribution

## Top Wallets By Normalized Row Count

| Rank | Wallet | Normalized rows |
| ---: | --- | ---: |
| 1 | `0x2ca4927174ba283d8a57f60ef3589844035a2930` | 192,555 |
| 2 | `0x55f389689b39fdd29d063f8b1aa776666a2dd788` | 124,810 |
| 3 | `0xf5d81a135f756ca16544e53c20fc20643ec3ad53` | 123,862 |
| 4 | `0xabfae5ef417fec83a63dcdbff5a13f71d09045c5` | 53,465 |
| 5 | `0xd4c1f7e8d876c4749228d515473d36f919583d1d` | 42,317 |
| 6 | `0xf4b8a39b7b828d8e059a55ed697a3dec634b6488` | 39,358 |
| 7 | `0xd02928c445d780ea954fe0b6f0be0f6cb9727678` | 37,937 |
| 8 | `0x348e5365acfa48a26ada7da840ca611e29c950ef` | 33,519 |
| 9 | `0x31dea2516beee92135b96f464eeec3cf292a13f2` | 33,270 |
| 10 | `0x5a7581618829f377a16be2338eabdd03fece0eaf` | 32,090 |
| 11 | `0x57dd78cd36e76e2011e8f6dc25cabbaba994494b` | 31,203 |
| 12 | `0xe29d84a6f37858d7f8017be454ee35726511e525` | 28,887 |
| 13 | `0x492322b1fca1ab301a103b716a243b20cb3001aa` | 28,755 |
| 14 | `0x2cb562384765bea1612ceb60007e315f904fbe86` | 28,135 |
| 15 | `0xbc927e87d072dfac3693846a83fa6922cc6c5f2a` | 25,833 |
| 16 | `0x0fd468a73084daa6ea77a9261e40fdec3e67e0c7` | 25,559 |
| 17 | `0xae7a0f9f663bb54bfe95378c7e3de7dd6e28d6bc` | 23,199 |
| 18 | `0x37c1e493c8a452ab3f5a6d01fda87795b91e7851` | 23,166 |
| 19 | `0x7b7f72a28fe109fa703eeed7984f2a8a68fedee2` | 21,851 |
| 20 | `0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00` | 20,420 |

## Top Wallets By Observed Row Notional

| Rank | Wallet | Observed row notional USD |
| ---: | --- | ---: |
| 1 | `0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00` | 374,462,783.88 |
| 2 | `0xf5d81a135f756ca16544e53c20fc20643ec3ad53` | 367,812,027.95 |
| 3 | `0xa6ee1ed1ae80b8352603654b39f5e7b9bedd5078` | 323,180,931.14 |
| 4 | `0x592838c5d6ffb870c20bf4f13d1089259354d5f9` | 312,577,806.07 |
| 5 | `0x7b7f72a28fe109fa703eeed7984f2a8a68fedee2` | 303,087,916.24 |
| 6 | `0xb8eb97eaed8367079894d2f1bed69bd220ec1dd5` | 272,393,136.75 |
| 7 | `0x32008fcb6bbd16532afc83ca8b6c920dde22c407` | 245,078,785.00 |
| 8 | `0x0fd468a73084daa6ea77a9261e40fdec3e67e0c7` | 239,479,548.81 |
| 9 | `0xf9109ada2f73c62e9889b45453065f0d99260a2d` | 231,121,073.64 |
| 10 | `0xd83cff88a32ffbf3951f2b13e4a0a37103b3193d` | 221,482,898.83 |
| 11 | `0x50b309f78e774a756a2230e1769729094cac9f20` | 207,002,690.51 |
| 12 | `0x57dd78cd36e76e2011e8f6dc25cabbaba994494b` | 200,706,340.79 |
| 13 | `0x09bc1cf4d9f0b59e1425a8fde4d4b1f7d3c9410d` | 193,579,837.57 |
| 14 | `0xd02928c445d780ea954fe0b6f0be0f6cb9727678` | 185,805,509.56 |
| 15 | `0xf4b8a39b7b828d8e059a55ed697a3dec634b6488` | 171,473,830.06 |
| 16 | `0x2d66f73159eaa54cc7fddaea2ba8cf91f9f14cd6` | 169,637,597.20 |
| 17 | `0x348e5365acfa48a26ada7da840ca611e29c950ef` | 169,313,907.60 |
| 18 | `0xd911e53d53b663972254e086450fd6198a25961e` | 158,497,390.34 |
| 19 | `0xd90647646547bacb7eb3a5af3023767fe4d9ec1c` | 156,121,451.21 |
| 20 | `0x7ca165f354e3260e2f8d5a7508cc9dd2fa009235` | 134,890,892.50 |

## Public Fill Enrichment For Top Activity Wallets

The top 10 activity wallets were queried with Hyperliquid `userFillsByTime` for the period after the local capture stopped.

Query window:

```text
2026-05-19T22:52:25.105000Z to 2026-05-23T04:20:24.380000Z
```

| Wallet | Fills returned | Notional estimate USD | First fill UTC | Last fill UTC | Cap hit |
| --- | ---: | ---: | --- | --- | --- |
| `0x2ca4927174ba283d8a57f60ef3589844035a2930` | 2,000 | 25,281.31 | `2026-05-22T04:27:10.863000Z` | `2026-05-22T06:57:19.331000Z` | yes |
| `0x55f389689b39fdd29d063f8b1aa776666a2dd788` | 2,000 | 30,252.23 | `2026-05-22T17:32:08.108000Z` | `2026-05-22T18:39:22.238000Z` | yes |
| `0xf5d81a135f756ca16544e53c20fc20643ec3ad53` | 2,000 | 2,286,785.20 | `2026-05-23T01:07:25.042000Z` | `2026-05-23T01:22:40.585000Z` | yes |
| `0xabfae5ef417fec83a63dcdbff5a13f71d09045c5` | 2,000 | 1,934,573.17 | `2026-05-21T09:01:05.109000Z` | `2026-05-21T12:46:14.838000Z` | yes |
| `0xd4c1f7e8d876c4749228d515473d36f919583d1d` | 2,000 | 1,927,089.28 | `2026-05-22T04:31:19.412000Z` | `2026-05-22T08:08:15.320000Z` | yes |
| `0xf4b8a39b7b828d8e059a55ed697a3dec634b6488` | 2,000 | 2,686,553.19 | `2026-05-19T22:55:18.279000Z` | `2026-05-20T03:26:27.111000Z` | yes |
| `0xd02928c445d780ea954fe0b6f0be0f6cb9727678` | 2,000 | 11,526,351.69 | `2026-05-19T23:00:05.366000Z` | `2026-05-20T08:49:06.509000Z` | yes |
| `0x348e5365acfa48a26ada7da840ca611e29c950ef` | 2,000 | 11,089,492.87 | `2026-05-19T23:00:02.026000Z` | `2026-05-20T10:23:25.158000Z` | yes |
| `0x31dea2516beee92135b96f464eeec3cf292a13f2` | 2,000 | 6,645,949.75 | `2026-05-21T19:18:03.111000Z` | `2026-05-22T03:21:13.661000Z` | yes |
| `0x5a7581618829f377a16be2338eabdd03fece0eaf` | 2,000 | 5,550,257.75 | `2026-05-19T22:58:30.761000Z` | `2026-05-20T03:09:44.313000Z` | yes |

## Provisional Follow-Up Queue

Start manual sanity checks with wallets that appear on both high-activity and high-notional screens:

- `0xf5d81a135f756ca16544e53c20fc20643ec3ad53`
- `0xd02928c445d780ea954fe0b6f0be0f6cb9727678`
- `0xf4b8a39b7b828d8e059a55ed697a3dec634b6488`
- `0x348e5365acfa48a26ada7da840ca611e29c950ef`
- `0x57dd78cd36e76e2011e8f6dc25cabbaba994494b`
- `0x7b7f72a28fe109fa703eeed7984f2a8a68fedee2`
- `0x0fd468a73084daa6ea77a9261e40fdec3e67e0c7`
- `0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00`

For each wallet, record:

- public profile or source availability
- whether activity looks directional, market-making, liquidation-driven, or unclear
- market concentration
- evidence of continued activity
- unsupported fields and caveats

This queue can seed issue #15, but it should stay labeled as an activity-derived candidate list until profitability attribution exists.
