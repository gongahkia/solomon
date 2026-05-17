# WhaleMirror Validation Gates

These gates are evidence collection flows, not one-shot tests. They are restartable: every sample appends to a JSON state file and regenerates a markdown report. Do not close the validation issues until elapsed time and evidence satisfy the gate.

## Gate Map

| Gate | GitHub issue | Minimum elapsed time | Command |
| --- | ---: | ---: | --- |
| Hyperliquid clean capture | #13 | 7 days | `stonks-cli whalemirror gates capture-sample` |
| Top-5 paper mirror | #14 | 30 days | `stonks-cli whalemirror gates paper-sample` |
| Live latency / slippage / scale | #10 | 60 days | `stonks-cli whalemirror gates live-sample` |

## Local Run

Use the bundled script to record one sample for all gates:

```console
$ scripts/whalemirror_gate_sample.sh
```

By default it writes runtime artifacts under `.cache/whalemirror-gates/`:

- `state/*.json`: restartable gate state
- `reports/*.md`: human-readable evidence summaries
- `captures/*.jsonl`: normalized capture samples

Override locations with:

```console
$ WHALEMIRROR_GATE_STATE_DIR=/path/state \
  WHALEMIRROR_GATE_REPORT_DIR=/path/reports \
  WHALEMIRROR_GATE_CAPTURE_DIR=/path/captures \
  scripts/whalemirror_gate_sample.sh
```

## Individual Commands

```console
$ stonks-cli whalemirror gates capture-sample \
    --state-dir .cache/whalemirror-gates/state \
    --capture-out-dir .cache/whalemirror-gates/captures \
    --report .cache/whalemirror-gates/reports/capture-gate.md

$ stonks-cli whalemirror gates paper-sample \
    --state-dir .cache/whalemirror-gates/state \
    --report .cache/whalemirror-gates/reports/paper-gate.md

$ stonks-cli whalemirror gates live-sample \
    --state-dir .cache/whalemirror-gates/state \
    --report .cache/whalemirror-gates/reports/live-gate.md

$ stonks-cli whalemirror gates status \
    --state-dir .cache/whalemirror-gates/state
```

Use `--reset` on a sample command only when intentionally starting a gate over.

## What Still Requires the Operator

- #13 needs the connector to run across real elapsed time. Fixture samples prove the harness, not the 7-day clean capture.
- #14 needs a selected top-5 wallet set and uninterrupted 30-day paper operation. Fixture samples prove risk-control reporting, not the gate.
- #10 needs live-arm decisions, latency evidence from real target-trade-to-order paths, live-vs-paper slippage records, and seven green weeks before notional caps can be raised.

The live sample fixture intentionally proves that a requested notional cap increase is blocked when the scale gate is not satisfied.
