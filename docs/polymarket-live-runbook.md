# Polymarket Live Runbook

## Install

1. Install the official Rust CLI:

```bash
./scripts/install_polymarket_cli.sh
```

2. Verify it:

```bash
polymarket --version
polymarket status
```

## Segregated Wallet

Use a separate wallet for first live testing.

- Do not reuse your main Polymarket wallet.
- Keep only test capital in it.
- Keep a small MATIC gas buffer for approvals and emergency actions.

Recommended first-pass wallet funding:

- `US$15-20` USDC for tiny test orders and one round-trip.
- `US$2-5` of MATIC equivalent for approvals and operational gas buffer.

At roughly `1 USD ~= 1.28 SGD` from recent April 2026 USD/SGD references, that is about:

- `S$19-26` in USDC
- `S$3-6` gas buffer
- practical total: `S$25-32`

Absolute floor:

- one `US$5` market-order style test is only about `S$6.40`, but that is too thin for a proper buy/cancel/sell validation sequence.

## Environment

Export these before live-mode testing:

```bash
export POLYMARKET_PRIVATE_KEY=0x...
export STONKS_CLI_POLYMARKET_LIVE_ARMED=1
```

Optional:

```bash
export POLYMARKET_SIGNATURE_TYPE=proxy
export POLYMARKET_CLI_BIN="$(command -v polymarket)"
```

Repo config minimum:

```json
{
  "polymarket": {
    "enabled": true,
    "paper": false,
    "rust_hotpath_enabled": true,
    "auto_trade_enabled": false,
    "live_require_armed_env": true,
    "max_position_fraction": 0.25,
    "max_market_notional": 10.0,
    "max_open_positions": 1,
    "max_live_open_orders": 1,
    "live_min_order_notional_usd": 5.0,
    "max_daily_loss": 10.0
  }
}
```

## Dry Run

Run the full dry-run script:

```bash
./scripts/polymarket_live_dry_run.sh
```

It will:

- run Rust tests
- run Python Polymarket tests
- verify `polymarket-cli`
- verify wallet visibility
- verify approvals command access
- verify collateral balance access
- run repo doctor with deep auth
- run read-only market sanity checks

## First Live Validation

Do this in order:

1. `polymarket approve check`
2. `polymarket clob balance --asset-type collateral`
3. `stonks-cli polymarket doctor --deep-auth`
4. place one tiny order manually with `polymarket clob create-order`
5. check `polymarket clob orders`
6. cancel it with `polymarket clob cancel ORDER_ID`
7. verify local repo journal and live-order state stayed consistent
8. only then allow `auto_trade_enabled=true`

## Rollout Limits

Suggested rollout:

1. manual read-only and cancel tests only
2. one tiny live order
3. one tiny buy and one tiny sell
4. one constrained runtime cycle with `max_open_positions=1`
5. several hours of supervised operation
6. overnight only after logs and reconciliation stay clean

## Stop Conditions

Do not scale up if any of these happen:

- doctor returns `fail`
- `approve check` is not clean
- collateral balance parsing is inconsistent
- order IDs in venue and local journal diverge
- stale cancel behavior is inconsistent
- partial fills produce incorrect local remaining size
- heartbeat or session behavior is unclear
