# stonks-cli

Encrypted, local-first portfolio intelligence for personal US/SG equity, ETF, and cash accounts.

It stores immutable encrypted source imports and a canonical transaction ledger, then reports holdings, cash, reconciliation, exposure, and performance. The first provider is Moomoo OpenD; portable CSV imports and provider plugins use the same contracts.

No command, plugin capability, MCP tool, or scheduler can unlock an account or submit/modify/cancel an order. Manual trading stays in the broker app.

## Start

```console
$ stonks-cli init-profile personal --key-file /absolute/path/personal.key
$ stonks-cli import-csv personal /absolute/path/export.csv --key-file /absolute/path/personal.key
$ stonks-cli portfolio personal --key-file /absolute/path/personal.key
```

`init-profile` generates a 256-bit key file with private permissions. Losing the key makes encrypted data unrecoverable. This private repository has no public license.
