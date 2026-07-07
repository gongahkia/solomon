# WhaleMirror 60-Day Live Gate

This is the operator path for #10. It records real Linux-hosted live-armed validation evidence only; fixture output from `stonks-cli whalemirror gates live-sample` remains a smoke test.

## Inputs

- Always-on Linux host with repo at `/opt/stonks-cli`.
- #14 paper gate passed.
- Explicit live arm with max live order notional below or equal to $50.
- Hyperliquid order and WebSocket evidence. Official docs: <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint> and <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats>.
- Live-vs-paper slippage report and public ledger/report artifacts.

## Evidence JSON

Write `${WHALEMIRROR_GATE_ROOT:-/var/lib/stonks-cli/whalemirror-gates}/reports/live-evidence.json`:

```json
{
  "source": "live_armed",
  "final_status": "completed",
  "runtime": {"os": "Linux"},
  "max_live_order_notional_usd": 49.0,
  "latency_report_path": "/var/lib/stonks-cli/whalemirror-gates/reports/live-latency.md",
  "slippage_report_path": "/var/lib/stonks-cli/whalemirror-gates/reports/live-vs-paper-slippage.md",
  "ledger_path": "/var/lib/stonks-cli/whalemirror-gates/reports/live-ledger.md",
  "latency_report": {
    "sample_count": 12,
    "p50_ms": 410.0,
    "p95_ms": 790.0,
    "failure_count": 1,
    "drop_context": ["ws_reconnect"]
  },
  "slippage_report": {
    "sample_count": 12,
    "avg_slippage_bps": 3.2,
    "max_slippage_bps": 9.1
  },
  "scale_gate": {
    "current_max_live_order_notional_usd": 49.0,
    "requested_max_live_order_notional_usd": 100.0,
    "effective_max_live_order_notional_usd": 49.0,
    "green_weeks": 6,
    "required_green_weeks": 7,
    "scale_gate_satisfied": false,
    "auto_raise_blocked": true
  }
}
```

If p95 latency exceeds 800ms, include `latency_reframe_path` linking the report that reframes the product away from fast copy.

## Record

```console
$ cd /opt/stonks-cli
$ WHALEMIRROR_GATE_ROOT=/var/lib/stonks-cli/whalemirror-gates \
  scripts/whalemirror_linux_live_60d.sh
```

The gate only passes when elapsed time is at least 60 days and the evidence includes Linux runtime metadata, completed live status, sub-$50 live cap, latency p50/p95/failure/drop context, live-vs-paper slippage summary, scale-gate guard proof, and ledger/report paths.

Current repo status: the actual 60-day live-armed run has not happened here.
