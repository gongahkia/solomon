# WhaleMirror Partial Capture Evidence - May 2026

## Decision

This capture is accepted as exploratory WhaleMirror evidence, but it does not close GitHub issue #13.

The useful finding is that the Hyperliquid ingestion path decoded a large Linux-hosted live sample cleanly while it was running. The blocking finding is that the run stopped before the 7-day target and never emitted `final_status: clean_capture`.

## Source Archive

Local archive:

```text
~/.local/state/stonks-cli/whalemirror-gates/archive/partial-2026-05-17-to-2026-05-20/
```

Primary local artifacts:

- `hyperliquid-raw.jsonl`
- `hyperliquid-normalized.jsonl`
- `capture-health.json`
- `executive-summary.md`
- `partial-capture-analysis.md`
- `hybrid-synthesis-extrapolation.md`
- `hybrid-synthesis-extrapolation.json`

## Real Capture Summary

| Metric | Value |
| --- | ---: |
| Started UTC | `2026-05-17T12:52:29.230430Z` |
| Last health update UTC | `2026-05-19T22:50:07.363088Z` |
| Reported duration | 57.7896 hours |
| 7-day target coverage | 34.40% |
| Raw JSONL lines | 763,206 |
| Normalized rows | 3,220,516 |
| Unique trade events | 1,608,667 |
| Unique wallets observed | 34,327 |
| Messages received | 762,869 |
| Decoded events | 3,422,194 |
| Decoded trades | 3,219,770 |
| Malformed messages | 0 |
| Dropped messages | 0 |
| Reconnects | 20 |

Last recorded error:

```text
no close frame received or sent
```

## Market Coverage

| Market | Real unique trade events | Real unique-event notional USD |
| --- | ---: | ---: |
| `BTC-PERP` | 952,212 | 4,784,966,638.44 |
| `ETH-PERP` | 419,260 | 2,307,080,981.23 |
| `SOL-PERP` | 237,195 | 478,747,966.07 |

## Synthetic Planning Estimate

The observed real capture rate extrapolates to the following 7-day planning estimates:

| Metric | Projection |
| --- | ---: |
| Projected 7-day normalized rows | 9,362,353 |
| Projected missing-window normalized rows | 6,141,837 |
| Projected 7-day unique trade events | 4,676,551 |
| Projected missing-window unique trade events | 3,067,884 |

These projections are planning estimates only. They are not validation evidence and must not be merged into real capture JSONL.

## Issue #13 Status

Status: not passed.

Useful evidence:

- The live connector ran on Linux.
- The connector decoded millions of live rows.
- While running, the sample had zero malformed messages and zero dropped messages.
- The dataset is large enough for exploratory analysis and activity-based candidate screening.

Blockers:

- The run stopped before the 7-day target.
- The run did not emit `final_status: clean_capture`.
- The previous status flow could report stale `running` evidence, which is now fixed by `capture_health_stale` detection.

## Allowed Uses

- Analyze connector quality.
- Build activity-based wallet shortlists.
- Size future storage and report jobs.
- Prepare public-source sanity checks for candidate wallets.
- Inform paper-mode assumptions.

## Disallowed Uses

- Closing issue #13.
- Claiming a completed 7-day clean capture.
- Claiming wallet alpha or profitability.
- Treating scraped or synthetic records as validation evidence.

## Follow-Up

The next 7-day capture should run under the systemd service described in `docs/whalemirror-validation-gates.md`. The partial dataset remains useful for exploratory work while the formal gate remains open.
