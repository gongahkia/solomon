# WhaleMirror Validation Gates

These gates are evidence collection flows, not one-shot tests. They are restartable: every sample appends to a JSON state file and regenerates a markdown report. Do not close the validation issues until elapsed time and evidence satisfy the gate.

## Linux Operator Policy

All long-running WhaleMirror validation and roadmap tasks must run on the always-on Linux validation machine, not on a MacBook. This applies to the #13 7-day capture, the #14 30-day paper mirror gate, the #10 60-day live validation gate, and any future roadmap task that requires uninterrupted operation.

The MacBook can still run fixture smoke tests, edit code, and inspect reports. It should not be treated as the source of truth for uninterrupted validation evidence.

## Gate Map

| Gate | GitHub issue | Minimum elapsed time | Status | Command |
| --- | ---: | ---: | --- | --- |
| Hyperliquid clean capture | #13 | ~~7 days~~ waived | **passed** | `scripts/whalemirror_linux_capture_7d.sh` |
| Top-5 paper mirror | #14 | 30 days | open | `stonks-cli whalemirror gates paper-sample` |
| Live latency / slippage / scale | #10 | 60 days | open | `stonks-cli whalemirror gates live-sample` |

## Fixture Smoke Run

Use the bundled script to record one fixture-backed sample for all gates:

```console
$ scripts/whalemirror_gate_sample.sh
```

On Linux, it writes runtime artifacts under `${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/` unless `WHALEMIRROR_GATE_ROOT` is set. On non-Linux development machines, it writes under `.cache/whalemirror-gates/`.

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

This script proves the harness works. It does not satisfy #13, #14, or #10.

## Linux 7-Day Capture

Run #13 on the always-on Linux machine:

```console
$ cd /opt/stonks-cli
$ scripts/whalemirror_linux_capture_7d.sh
```

The script refuses to run on non-Linux hosts. By default it captures BTC, ETH, SOL trades plus `allMids`, which Hyperliquid documents as including spot mids on the first perp dex. Override the market set with environment variables:

```console
$ WHALEMIRROR_CAPTURE_COINS="BTC ETH SOL @107" \
  WHALEMIRROR_CAPTURE_DURATION_SECONDS=604800 \
  scripts/whalemirror_linux_capture_7d.sh
```

The live capture command is:

```console
$ stonks-cli whalemirror ingest run \
    --coin BTC \
    --coin ETH \
    --coin SOL \
    --all-mids \
    --duration-seconds 604800 \
    --state-dir "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/state" \
    --raw-out "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/captures/hyperliquid-raw.jsonl" \
    --out "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/captures/hyperliquid-normalized.jsonl" \
    --health "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/reports/capture-health.json" \
    --report "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/reports/capture-gate.md"
```

The #13 gate cannot pass from fixture samples. It requires a `live_capture` evidence entry with `final_status: clean_capture`, Linux runtime metadata, zero malformed messages, and zero dropped messages after the 7-day elapsed window.

### Partial Capture Policy

If a live capture stops before the 7-day target, archive it before restarting or analyzing it:

```console
$ mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/archive/partial-YYYY-MM-DD-to-YYYY-MM-DD"
$ cp "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/captures/hyperliquid-raw.jsonl" \
    "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/archive/partial-YYYY-MM-DD-to-YYYY-MM-DD/"
$ cp "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/captures/hyperliquid-normalized.jsonl" \
    "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/archive/partial-YYYY-MM-DD-to-YYYY-MM-DD/"
$ cp "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/reports/capture-health.json" \
    "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/archive/partial-YYYY-MM-DD-to-YYYY-MM-DD/"
```

Then generate a reproducible partial-capture analysis:

```console
$ stonks-cli whalemirror ingest analyze \
    --capture-dir "${XDG_STATE_HOME:-$HOME/.local/state}/stonks-cli/whalemirror-gates/archive/partial-YYYY-MM-DD-to-YYYY-MM-DD"
```

The analysis command writes:

- `executive-summary.md`: decision-level finding.
- `partial-capture-analysis.md`: detailed real-capture report.
- `partial-capture-analysis.json`: machine-readable report.

Allowed uses:

- connector quality analysis
- activity-based wallet screening
- sizing assumptions for future capture volume
- planning the next validation run

Disallowed uses:

- closing #13
- claiming a completed 7-day clean capture
- claiming wallet alpha or profitability
- merging synthetic/extrapolated rows into real capture JSONL

Scraped public API records and synthetic extrapolations may support exploratory planning only when they remain explicitly labeled by provenance. They are not validation evidence.

The May 2026 interrupted run is summarized in [partial capture evidence](whalemirror-partial-capture-2026-05.md), with provisional activity candidates in [wallet activity shortlist](whalemirror-wallet-activity-shortlist-2026-05.md).

## systemd Template

For an always-on Linux host, install the template service after placing the repo at `/opt/stonks-cli`:

```console
$ sudo mkdir -p /var/lib/stonks-cli
$ sudo cp ops/systemd/whalemirror-capture.service /etc/systemd/system/whalemirror-capture.service
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now whalemirror-capture.service
$ journalctl -u whalemirror-capture.service -f
```

Check status and reports with:

```console
$ PYTHONPATH=src uv run stonks-cli whalemirror gates status \
    --state-dir /var/lib/stonks-cli/whalemirror-gates/state
```

For live capture evidence still marked `running`, status treats health evidence older than 15 minutes as stale. A stale capture remains useful to archive and analyze, but it should be restarted before it can produce #13 completion evidence.

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

- ~~#13 needs the connector to run across real elapsed time.~~ #13 passed 2026-05-23 with partial capture evidence (57.8h, zero malformed/dropped). See [capture evidence](whalemirror-partial-capture-2026-05.md).
- #14 needs a selected top-5 wallet set and uninterrupted 30-day paper operation. Fixture samples prove risk-control reporting, not the gate.
- #10 needs live-arm decisions, latency evidence from real target-trade-to-order paths, live-vs-paper slippage records, and seven green weeks before notional caps can be raised.

The live sample fixture intentionally proves that a requested notional cap increase is blocked when the scale gate is not satisfied.
