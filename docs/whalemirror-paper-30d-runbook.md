# WhaleMirror 30-Day Paper Gate

This is the operator path for #14. It records real Linux-hosted paper evidence only; fixture output from `stonks-cli whalemirror gates paper-sample` remains a smoke test.

## Inputs

- Always-on Linux host with repo at `/opt/stonks-cli`.
- Top 5 eligible Hyperliquid wallets from reproducible ranking output.
- Hyperliquid WebSocket feeds for `userFills`, `userFundings`, and `allMids`; official subscription docs: <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions>.
- Complete paper journal and ledger for 30 elapsed days.

## Evidence JSON

Write `${WHALEMIRROR_GATE_ROOT:-/var/lib/stonks-cli/whalemirror-gates}/reports/paper-evidence.json`:

```json
{
  "source": "live_paper",
  "final_status": "completed",
  "runtime": {"os": "Linux"},
  "selected_wallets": ["0x...", "0x...", "0x...", "0x...", "0x..."],
  "ledger_path": "/var/lib/stonks-cli/whalemirror-gates/reports/paper-ledger.md",
  "journal_path": "/var/lib/stonks-cli/whalemirror-gates/reports/paper-journal.jsonl",
  "report_path": "/var/lib/stonks-cli/whalemirror-gates/reports/paper-gate.md",
  "risk_controls": ["paper_mirror_open", "risk_cap", "stop_loss", "cooldown"],
  "tearsheet": {
    "closed_trades": 2,
    "open_positions": 0,
    "wins": 1,
    "losses": 1,
    "realized_pnl_usd": -1.5,
    "expectancy_usd": -0.75,
    "sharpe": -0.2,
    "max_drawdown_usd": 5.0,
    "risk_cap_skips": 1,
    "stop_loss_exits": 1,
    "cooldown_blocks": 1,
    "skipped_trades": 2
  }
}
```

## Record

```console
$ cd /opt/stonks-cli
$ WHALEMIRROR_GATE_ROOT=/var/lib/stonks-cli/whalemirror-gates \
  scripts/whalemirror_linux_paper_30d.sh
```

The gate only passes when elapsed time is at least 30 days and the evidence includes Linux runtime metadata, five selected wallets, ledger/journal/report paths, win and loss outcomes, PnL, expectancy, Sharpe, drawdown, risk-cap skips, stop-loss exits, cooldown blocks, and skipped trades.

Current repo status: #15 produced public sanity checks but did not identify five eligible live targets. Until that exists and a Linux paper journal runs for 30 days, #14 remains open.
