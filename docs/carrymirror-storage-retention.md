# CarryMirror Storage And Retention

Status: accepted for GitHub issue #18.

CarryMirror uses SQLite at `carrymirror.sqlite3` under the app state directory.

SQLite is the first storage backend because it is in the Python standard library, runs on Raspberry Pi OS without an extra database service, handles small append-heavy bot state, and is adequate for BTC/ETH carry scanner, paper engine, risk checks, reconciliation, and reports. DuckDB remains a later analytics export option, not the primary Pi write path.

## Tables

| Table | Purpose |
| --- | --- |
| `carry_quotes` | Raw spot/perp/oracle/mark quotes and source health. |
| `carry_funding_snapshots` | Funding rates, annualized rates, premium index, and next funding time. |
| `carry_basis_snapshots` | Spot/perp basis and annualized basis snapshots. |
| `carry_decisions` | Audit decisions keyed by `decision_id`; retention does not delete these rows. |
| `carry_positions` | Position snapshots for paper/live state, margin buffer, delta, funding, and liquidation distance. |
| `carry_venue_health` | Venue health samples used by stale-data and degradation gates. |
| `carry_daily_aggregates` | Daily compacted aggregates for old raw quote, funding, basis, position, and venue-health rows. |

## Retention

Default raw retention is 7 days. Default aggregate retention is 180 days.

The retention job first compacts old raw rows into `carry_daily_aggregates`, then deletes raw rows older than the raw cutoff. `carry_decisions` is audit data and is not deleted by retention. Running retention repeatedly is idempotent: already-compacted days are upserted by `(kind, bucket_date, venue, asset)`, and subsequent runs keep the aggregate while finding no old raw rows.

This policy bounds high-churn snapshot storage on a 56GB Raspberry Pi SD card while preserving decision audit rows and daily derived evidence for reporting.
