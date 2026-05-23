# WhaleMirror Wallet Sanity Checks (#15)

Structured sanity checks for the 8 provisional wallets from the [May 2026 activity shortlist](whalemirror-wallet-activity-shortlist-2026-05.md). Each wallet must be classified before it can enter the top-5 set for #14.

## Check Criteria

For each wallet:

1. **Public profile**: Is the wallet visible on `hyperdash.info` or `hyperliquid.xyz` leaderboards?
2. **Activity type**: directional / market-making / liquidation-driven / unclear
3. **Market concentration**: single-market or multi-market?
4. **Continued activity**: evidence of activity after the capture window (May 19–23)?
5. **Unsupported fields**: what data is missing that would change the classification?

## Wallet Checks

### 1. `0xf5d81a135f756ca16544e53c20fc20643ec3ad53`

- **Row count**: 123,862 | **Notional**: $367.8M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: 2,000 fills returned (cap hit), $2.3M notional in ~15min window
- **Caveats**: TODO
- **Verdict**: TODO

### 2. `0xd02928c445d780ea954fe0b6f0be0f6cb9727678`

- **Row count**: 37,937 | **Notional**: $185.8M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: 2,000 fills returned (cap hit), $11.5M notional in ~10h window
- **Caveats**: TODO
- **Verdict**: TODO

### 3. `0xf4b8a39b7b828d8e059a55ed697a3dec634b6488`

- **Row count**: 39,358 | **Notional**: $171.5M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: 2,000 fills returned (cap hit), $2.7M notional in ~4.5h window
- **Caveats**: TODO
- **Verdict**: TODO

### 4. `0x348e5365acfa48a26ada7da840ca611e29c950ef`

- **Row count**: 33,519 | **Notional**: $169.3M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: 2,000 fills returned (cap hit), $11.1M notional in ~11h window
- **Caveats**: TODO
- **Verdict**: TODO

### 5. `0x57dd78cd36e76e2011e8f6dc25cabbaba994494b`

- **Row count**: 31,203 | **Notional**: $200.7M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: not queried in enrichment batch
- **Caveats**: TODO
- **Verdict**: TODO

### 6. `0x7b7f72a28fe109fa703eeed7984f2a8a68fedee2`

- **Row count**: 21,851 | **Notional**: $303.1M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: not queried in enrichment batch
- **Caveats**: TODO
- **Verdict**: TODO

### 7. `0x0fd468a73084daa6ea77a9261e40fdec3e67e0c7`

- **Row count**: 25,559 | **Notional**: $239.5M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: not queried in enrichment batch
- **Caveats**: TODO
- **Verdict**: TODO

### 8. `0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00`

- **Row count**: 20,420 | **Notional**: $374.5M
- **Public profile**: TODO
- **Activity type**: TODO
- **Market concentration**: TODO
- **Continued activity**: not queried in enrichment batch
- **Caveats**: TODO
- **Verdict**: TODO

## Selection for #14

Once at least 5 wallets have a verdict of `directional_candidate` or stronger, select them as the top-5 set for the 30-day paper mirror gate (#14). Record the selection rationale in the [decision ledger](decision-ledger.md).

## Hard Constraints

- Do not claim profitability without closed-outcome attribution.
- High activity can be market-making or liquidation flow, not necessarily directional skill.
- The `userFillsByTime` API returns a max of 2,000 rows per query — all enrichment queries hit this cap.
