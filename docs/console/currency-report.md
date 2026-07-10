<!-- SPDX-License-Identifier: Apache-2.0 -->

# Currency Report

`GET /console/currency-report` renders the partner-facing report for a period and scope.

Layout:

| Left pane | Right pane |
|---|---|
| period, scope, practice, matter, client filters | movement rows |
| stale / contradictory / superseded / retired totals | authority moved, current verification status, reason |
| export JSON / export PDF | dependent-item count |

Exports:

- `GET /console/currency-report/export?format=json` returns an audit-pack-shaped JSON payload with manifest, report, and journal.
- `GET /console/currency-report/export?format=pdf` returns a human-readable report PDF.
