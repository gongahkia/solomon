# CarryMirror Tiny-Live Runbook

Status: fail-closed scaffold for GitHub issue #25.

This is not permission to trade. Live remains blocked until the preflight below passes.

## Arm Path

Required:

- `carrymirror.live_armed=true`.
- `STONKS_CLI_CARRY_LIVE_ARMED=armed`.
- `carrymirror.max_total_live_usd` manually configured between USD 50 and USD 200.
- `--cap-usd` manual confirmation matching config exactly.
- Separate secrets file at `carrymirror.live_secrets_path`.
- 30-day paper gate passed.
- SG legal review recorded.
- Fresh venue health.
- Reconciliation report has no live blockers.

Check only:

```sh
stonks-cli carry live preflight \
  --paper-gate-passed \
  --legal-review-recorded \
  --venue-health-ok \
  --manual-cap-confirmed \
  --requested-notional-usd 50 \
  --cap-usd 50 \
  --secrets-path ~/.config/stonks-cli/carry-live.env
```

## Executor Policy

- Entry planning creates spot and perp order intents before either leg can be submitted.
- Entry orders use post-only `Alo`.
- Exit planning uses IOC orders; the perp exit leg is reduce-only.
- If only one leg fills and timeout expires, recovery exits the unhedged leg instead of scaling.
- Live reconciliation blocks on account/position mismatch or missing ledger rows.
- No code path raises live caps automatically.

## 60-Day Tiny-Live Validation

Record:

- Start/end.
- Capital source.
- Configured cap.
- All preflight outputs.
- Every order plan, fill, partial-fill recovery, reduce-only exit, reconciliation report, and ledger row.
- Daily realized/unrealized PnL after funding, fees, slippage, borrow/carry cost, and volatility buffer.
- All risk incidents.

Pass criteria:

- USD 50-200 cap never exceeded.
- Seven green weeks.
- Zero unresolved risk incidents.
- Zero unresolved reconciliation mismatches.
- No automatic scale proposal or cap increase.
