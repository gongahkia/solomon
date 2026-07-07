#!/usr/bin/env bash
set -euo pipefail

: "${STONKS_CLI_CARRY_STATE_DIR:=/var/lib/stonks-cli/carry-paper}"
: "${STONKS_CLI_CARRY_SOAK_SECONDS:=604800}"
: "${STONKS_CLI_CARRY_INTERVAL_SECONDS:=300}"

if command -v stonks-cli >/dev/null 2>&1; then
  STONKS_CLI_BIN=(stonks-cli)
elif command -v uv >/dev/null 2>&1; then
  STONKS_CLI_BIN=(uv run stonks-cli)
else
  echo "missing stonks-cli or uv" >&2
  exit 127
fi

soak_dir="$STONKS_CLI_CARRY_STATE_DIR/soak/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$soak_dir"
end_at=$((SECONDS + STONKS_CLI_CARRY_SOAK_SECONDS))

while [ "$SECONDS" -lt "$end_at" ]; do
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"

  {
    date -u
    uptime || true
    df -Pk "$STONKS_CLI_CARRY_STATE_DIR" || true
    if [ -r /proc/meminfo ]; then sed -n '1,5p' /proc/meminfo; fi
    if [ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq ]; then cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq; fi
  } > "$soak_dir/host-$run_id.txt"

  "${STONKS_CLI_BIN[@]}" carry health \
    --state-dir "$STONKS_CLI_CARRY_STATE_DIR" \
    --ledger "$STONKS_CLI_CARRY_STATE_DIR/latest-ledger.md" \
    --stream-heartbeat "$STONKS_CLI_CARRY_STATE_DIR/carry-stream-heartbeat.json" \
    --reconciliation "$STONKS_CLI_CARRY_STATE_DIR/latest-reconciliation.md" \
    --json > "$soak_dir/health-$run_id.json"

  "${STONKS_CLI_BIN[@]}" carry scan \
    --asset BTC \
    --asset ETH \
    --json > "$soak_dir/scan-$run_id.json"

  sleep "$STONKS_CLI_CARRY_INTERVAL_SECONDS"
done
