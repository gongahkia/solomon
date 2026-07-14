# stonks-cli Capture Validation

The capture gate is a restartable Linux-hosted evidence flow for the historical Hyperliquid connector validation. Fixture samples prove only the harness.

| Gate | Issue | Status | Command |
| --- | ---: | --- | --- |
| Hyperliquid clean capture | #13 | passed | `scripts/linux_capture_7d.sh` |

Run a fixture smoke sample with:

```console
$ scripts/gate_capture_sample.sh
```

Run the elapsed-time capture only on the always-on Linux host:

```console
$ stonks-cli run-ingest --coin BTC --coin ETH --coin SOL --all-mids --duration-seconds 604800
```

A completion record needs Linux runtime metadata, `final_status: clean_capture`, and zero malformed or dropped messages. Store state and reports under `/var/lib/stonks-cli/validation-gates/` on the operator host.

Issue #14 is not a wallet-copy gate. Its active contract is the [30-day carry paper gate](carry-30d-paper-gate.md).
