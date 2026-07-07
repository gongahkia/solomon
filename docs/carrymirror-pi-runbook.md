# CarryMirror Raspberry Pi Runbook

Status: ops scaffold for GitHub issue #24.

## Install

1. Create `stonks` user and clone this repo to `/opt/stonks-cli`.
2. Install `uv`, then run `uv sync` from `/opt/stonks-cli`.
3. Create `/etc/stonks-cli/carrymirror.env` readable only by `stonks`.
4. Create `/var/lib/stonks-cli/carry-paper` and `/var/log/stonks-cli`, owned by `stonks`.
5. Copy `ops/systemd/carrymirror-paper.service` to `/etc/systemd/system/`.
6. Copy `ops/logrotate/carrymirror-paper` to `/etc/logrotate.d/`.
7. Run `systemctl daemon-reload && systemctl enable --now carrymirror-paper.service`.

## Secrets

`/etc/stonks-cli/carrymirror.env`:

```sh
STONKS_CLI_CONFIG=/etc/stonks-cli/config.json
STONKS_CLI_CARRY_STATE_DIR=/var/lib/stonks-cli/carry-paper
STONKS_CLI_CARRY_DURATION_HOURS=24
STONKS_CLI_CARRY_INTERVAL_SECONDS=300
STONKS_CLI_CARRY_SOAK_SECONDS=604800
STONKS_CLI_CARRY_TELEGRAM_BOT_TOKEN=
STONKS_CLI_CARRY_TELEGRAM_CHAT_ID=
STONKS_CLI_CARRY_EMAIL_SMTP_URL=
STONKS_CLI_CARRY_EMAIL_TO=
```

## Health

Run before and after service restart:

```sh
stonks-cli carry health \
  --state-dir /var/lib/stonks-cli/carry-paper \
  --ledger /var/lib/stonks-cli/carry-paper/latest-ledger.md \
  --stream-heartbeat /var/lib/stonks-cli/carry-paper/carry-stream-heartbeat.json \
  --reconciliation /var/lib/stonks-cli/carry-paper/latest-reconciliation.md \
  --json
```

Health output covers host, storage, time sync, network, venue API, stream freshness, ledger/reconciliation state, and alert sink state.

## Alerts

Set `carrymirror.alert_sink` to `telegram` or `email` in config. Required events are `kill_switch`, `stale_data`, `ledger_mismatch`, and `service_restart`.

## Runtime

- Service restart policy: `Restart=always`, `RestartSec=30`, `RuntimeMaxSec=86400`.
- Watchdog setting: `WatchdogSec=300`.
- Bounded logs: `/var/log/stonks-cli/carrymirror-paper.log` with `ops/logrotate/carrymirror-paper`.
- State: `/var/lib/stonks-cli/carry-paper`, with timestamped runs under `runs/` and `latest-*` symlinks.
- Backup: copy state dir, config, env file, logs, ledger, and reports daily.
- Cooling: use a case fan or active cooler; record CPU throttling during soak reports.

## Gates

- 7-day dry Pi soak: run `scripts/carrymirror_pi_scan_soak.sh`; it writes scanner, health, CPU, RAM, disk, reconnect/data-gap evidence under `soak/`.
- 30-day paper carry gate: run `carrymirror-paper.service`; it writes timestamped paper state/report/ledger artifacts under `runs/`.
- Live work remains blocked until both reports pass and no unresolved reconciliation/risk/alert failures remain.
