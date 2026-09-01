#!/bin/sh
# SPDX-License-Identifier: Apache-2.0

# Disposable, vendor-neutral production-profile backup/restore rehearsal. It
# creates isolated containers and state under mktemp, then removes only those
# exact resources on exit.
set -eu

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required for the production operations rehearsal" >&2
    exit 2
fi
if ! command -v python >/dev/null 2>&1; then
    echo "python is required for the production operations rehearsal" >&2
    exit 2
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
run_id="solomon-operations-$$"
image="${SOLOMON_OPERATIONS_IMAGE:-solomon-operations-rehearsal:local}"
network="${run_id}-network"
source_pg="${run_id}-source-pg"
restore_pg="${run_id}-restore-pg"
work="$(mktemp -d "${TMPDIR:-/tmp}/solomon-operations.XXXXXX")"
state="$work/state"
mkdir "$state"
chmod 0777 "$state"
umask 077
report_path="${SOLOMON_OPERATIONS_REPORT_PATH:-}"
if [ -n "$report_path" ] && [ -e "$report_path" ]; then
    echo "rehearsal report path must not already exist" >&2
    exit 2
fi

monotonic_ns() {
    python -c 'import time; print(time.monotonic_ns())'
}

rehearsal_started_ns="$(monotonic_ns)"

cleanup() {
    status=$?
    docker rm --force "$source_pg" "$restore_pg" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    # The service runs as an unprivileged UID and can own files beneath this
    # exact mktemp directory.  Remove only this run's contents via the same
    # disposable image, then remove the now-empty host directory.
    docker run --rm -v "$work:/state" --entrypoint /bin/sh "$image" \
        -c 'find /state -mindepth 1 -delete' >/dev/null 2>&1 || true
    rmdir "$work" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

wait_for_postgres() {
    name="$1"
    attempts=0
    while ! docker exec "$name" pg_isready -U solomon -d solomon >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 60 ]; then
            echo "PostgreSQL did not become ready within 60 seconds" >&2
            exit 1
        fi
        sleep 1
    done
}

docker build --quiet -t "$image" "$root" >/dev/null
docker network create "$network" >/dev/null
for name in "$source_pg" "$restore_pg"; do
    docker run --detach --rm --name "$name" --network "$network" \
        -e POSTGRES_DB=solomon \
        -e POSTGRES_USER=solomon \
        -e POSTGRES_PASSWORD=disposable-postgres-password \
        pgvector/pgvector:0.8.2-pg16-bookworm >/dev/null
    wait_for_postgres "$name"
done

source_url="postgresql://solomon:disposable-postgres-password@${source_pg}:5432/solomon"
restore_url="postgresql://solomon:disposable-postgres-password@${restore_pg}:5432/solomon"

source_run() {
    timeout 120 docker run --rm --network "$network" \
        -v "$state:/state" \
        -v "$root/examples:/app/examples:ro" \
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$source_url" \
        -e SOLOMON_DATA_DIR=/state/source-data \
        -e SOLOMON_JOURNAL_DIR=/state/source-journal \
        -e SOLOMON_BACKUP_PASSPHRASE=disposable-backup-passphrase \
        "$image" "$@"
}

restore_run() {
    timeout 120 docker run --rm --network "$network" \
        -v "$state:/state" \
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$restore_url" \
        -e SOLOMON_RESTORE_DATABASE_URL="$restore_url" \
        -e SOLOMON_DATA_DIR=/tmp/restore-control-data \
        -e SOLOMON_JOURNAL_DIR=/tmp/restore-control-journal \
        -e SOLOMON_BACKUP_PASSPHRASE=disposable-backup-passphrase \
        "$image" "$@"
}

restored_run() {
    timeout 120 docker run --rm --network "$network" \
        -v "$state:/state" \
        -v "$root/examples:/app/examples:ro" \
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$restore_url" \
        -e SOLOMON_DATA_DIR=/state/restored/data \
        -e SOLOMON_JOURNAL_DIR=/state/restored/journal \
        "$image" "$@"
}

initialization_started_ns="$(monotonic_ns)"
source_run solomon migrate >/dev/null
source_run solomon deployment init --owner rehearsal >/dev/null
source_run solomon deployment preflight --require-initialized --format json >/dev/null
initialization_completed_ns="$(monotonic_ns)"
fixture_started_ns="$(monotonic_ns)"
source_run python /app/examples/scenarios/governed-dependency-assertion-proof/run.py \
    --workspace /state/source-proof \
    --data-dir /state/source-data \
    --journal-dir /state/source-journal \
    --database-url "$source_url" \
    --audit-pack-dir /state/source-data/pre-backup-audit-pack \
    --queue-recovery-operation \
    --serial-confirmation > "$work/source-fixture.json"
fixture_completed_ns="$(monotonic_ns)"
source_run solomon consistency check --matter-id matter-alpha --client-id client-alpha > "$work/source-consistency.json"
source_run solomon deployment verify --matter-id matter-alpha --client-id client-alpha --format json > "$work/source-verify.json"
backup_started_ns="$(monotonic_ns)"
source_run solomon deployment backup /state/checkpoint.enc >/dev/null
backup_completed_ns="$(monotonic_ns)"
backup_inspection_started_ns="$(monotonic_ns)"
source_run solomon deployment backup-inspect /state/checkpoint.enc >/dev/null
backup_inspection_completed_ns="$(monotonic_ns)"
source_run solomon health > "$work/source-health.json"
source_run python -c 'import json; from solomon.api.service import SolomonService; from solomon.config import get_settings; from solomon.semantic_inventory import semantic_inventory; s=get_settings(); print(json.dumps(semantic_inventory(SolomonService(data_dir=s.data_dir, journal_dir=s.journal_dir, database_url=s.database_url)), sort_keys=True))' > "$work/source-inventory.json"

restore_plan_started_ns="$(monotonic_ns)"
restore_run solomon deployment restore-plan /state/checkpoint.enc /state/restored --output /state/restore-plan.json >/dev/null
restore_plan_completed_ns="$(monotonic_ns)"
restore_tables="$(docker exec "$restore_pg" psql -U solomon -d solomon -Atc \
    "SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_schema <> 'information_schema' AND table_schema NOT LIKE 'pg_%' AND table_type = 'BASE TABLE' ORDER BY 1")"
if [ -n "$restore_tables" ]; then
    echo "restore target contains application tables before restore" >&2
    printf '%s\n' "$restore_tables" >&2
    exit 1
fi
restore_apply_started_ns="$(monotonic_ns)"
restore_run solomon deployment restore --plan /state/restore-plan.json --apply >/dev/null
restore_apply_completed_ns="$(monotonic_ns)"
post_restore_validation_started_ns="$(monotonic_ns)"
restored_run solomon deployment preflight --require-initialized --format json >/dev/null
restored_run solomon health > "$work/restored-health.json"
restored_run solomon consistency check --matter-id matter-alpha --client-id client-alpha > "$work/restored-consistency.json"
restored_run solomon deployment verify --matter-id matter-alpha --client-id client-alpha --format json > "$work/restored-verify.json"
restored_run python -c 'import json; from solomon.audit.journal import AuditJournal; print(json.dumps(AuditJournal.verify_pack("/state/restored/data/pre-backup-audit-pack").model_dump(mode="json"), sort_keys=True))' > "$work/restored-audit-pack.json"
restored_run python -c 'import json; from solomon.api.service import SolomonService; from solomon.config import get_settings; from solomon.semantic_inventory import semantic_inventory; s=get_settings(); print(json.dumps(semantic_inventory(SolomonService(data_dir=s.data_dir, journal_dir=s.journal_dir, database_url=s.database_url)), sort_keys=True))' > "$work/restored-inventory.json"
restored_run python -c 'import json; from solomon.api.service import SolomonService; from solomon.config import get_settings; from solomon.worker import run_pending_operations; s=get_settings(); service=SolomonService(data_dir=s.data_dir, journal_dir=s.journal_dir, database_url=s.database_url); print(json.dumps(run_pending_operations(service, worker_id="backup-recovery-worker").model_dump(mode="json"), sort_keys=True))' > "$work/recovery-worker.json"
restored_run solomon consistency check --matter-id matter-alpha --client-id client-alpha > "$work/restored-recovery-consistency.json"
restored_run solomon deployment verify --matter-id matter-alpha --client-id client-alpha --format json > "$work/recovered-verify.json"
restored_run python /app/examples/scenarios/governed-dependency-assertion-proof/run.py \
    --workspace /state/restored-proof \
    --data-dir /state/restored/data \
    --journal-dir /state/restored/journal \
    --database-url "$restore_url" \
    --post-restore-write > "$work/post-restore-write.json"
post_restore_validation_completed_ns="$(monotonic_ns)"
rehearsal_completed_ns="$(monotonic_ns)"

python - "$work/source-health.json" "$work/restored-health.json" "$work/source-inventory.json" "$work/restored-inventory.json" "$work/source-fixture.json" "$work/source-consistency.json" "$work/restored-consistency.json" "$work/source-verify.json" "$work/restored-verify.json" "$work/restored-audit-pack.json" "$work/recovery-worker.json" "$work/restored-recovery-consistency.json" "$work/recovered-verify.json" "$work/post-restore-write.json" "$report_path" "$rehearsal_started_ns" "$initialization_started_ns" "$initialization_completed_ns" "$fixture_started_ns" "$fixture_completed_ns" "$backup_started_ns" "$backup_completed_ns" "$backup_inspection_started_ns" "$backup_inspection_completed_ns" "$restore_plan_started_ns" "$restore_plan_completed_ns" "$restore_apply_started_ns" "$restore_apply_completed_ns" "$post_restore_validation_started_ns" "$post_restore_validation_completed_ns" "$rehearsal_completed_ns" <<'PY'
import json
import sys
from pathlib import Path

source = json.load(open(sys.argv[1], encoding="utf-8"))
restored = json.load(open(sys.argv[2], encoding="utf-8"))
source_inventory = json.load(open(sys.argv[3], encoding="utf-8"))
restored_inventory = json.load(open(sys.argv[4], encoding="utf-8"))
source_fixture = json.load(open(sys.argv[5], encoding="utf-8"))
source_consistency = json.load(open(sys.argv[6], encoding="utf-8"))
restored_consistency = json.load(open(sys.argv[7], encoding="utf-8"))
source_verify = json.load(open(sys.argv[8], encoding="utf-8"))
restored_verify = json.load(open(sys.argv[9], encoding="utf-8"))
restored_audit_pack = json.load(open(sys.argv[10], encoding="utf-8"))
recovery_worker = json.load(open(sys.argv[11], encoding="utf-8"))
restored_recovery_consistency = json.load(open(sys.argv[12], encoding="utf-8"))
recovered_verify = json.load(open(sys.argv[13], encoding="utf-8"))
post_restore_write = json.load(open(sys.argv[14], encoding="utf-8"))
if source["store"]["item_count"] != restored["store"]["item_count"]:
    raise SystemExit("restored knowledge inventory differs from checkpoint")
if not source["journal"]["ok"] or not restored["journal"]["ok"]:
    raise SystemExit("source or restored audit journal failed verification")
if source_inventory != restored_inventory:
    differences = {
        component: {
            "source": source_inventory["components"].get(component),
            "restored": restored_inventory["components"].get(component),
        }
        for component in sorted(set(source_inventory["components"]) | set(restored_inventory["components"]))
        if source_inventory["components"].get(component) != restored_inventory["components"].get(component)
    }
    raise SystemExit(f"restored semantic inventory differs from checkpoint: {json.dumps(differences, sort_keys=True)}")
if source_consistency["findings"] or restored_consistency["findings"]:
    raise SystemExit("fixture deployment has consistency findings")
if source_verify["state"] != "degraded" or restored_verify["state"] != "degraded":
    raise SystemExit("queued operation was not visible in source or restored deployment verification")
if not source_fixture["audit"]["audit_pack_verified"]:
    raise SystemExit("fixture audit pack failed verification before backup")
if not restored_audit_pack["ok"]:
    raise SystemExit("restored audit pack failed verification")
if not source_fixture.get("operation_recovery", {}).get("queued_confirmation"):
    raise SystemExit("fixture did not include a recoverable operation")
if recovery_worker["completed"] < 1 or recovery_worker["failed"] or recovery_worker["terminal"]:
    raise SystemExit("restored worker did not safely resume the queued operation")
if restored_recovery_consistency["findings"]:
    raise SystemExit("recovered fixture has consistency findings")
if recovered_verify["state"] != "ready":
    raise SystemExit("deployment verification did not return to ready after operation recovery")
if post_restore_write["result"] != "passed" or not post_restore_write["edge_provenance_matches"]:
    raise SystemExit("post-restore governed write did not retain edge provenance")

timestamps = [int(value) for value in sys.argv[16:]]
(
    rehearsal_started,
    initialization_started,
    initialization_completed,
    fixture_started,
    fixture_completed,
    backup_started,
    backup_completed,
    backup_inspection_started,
    backup_inspection_completed,
    restore_plan_started,
    restore_plan_completed,
    restore_apply_started,
    restore_apply_completed,
    post_restore_validation_started,
    post_restore_validation_completed,
    rehearsal_completed,
) = timestamps

def seconds(start: int, completed: int) -> float:
    return round((completed - start) / 1_000_000_000, 6)

result = {
    "schema_id": "solomon.production_operations_rehearsal.v3",
    "profile": "mixed-postgresql-sqlite",
    "source_item_count": source["store"]["item_count"],
    "restored_item_count": restored["store"]["item_count"],
    "source_audit_entries": source["journal"]["entries"],
    "restored_audit_entries": restored["journal"]["entries"],
    "semantic_inventory": {
        component: summary["count"] for component, summary in source_inventory["components"].items()
    },
    "semantic_inventory_equal": True,
    "fixture": source_fixture,
    "source_verification": source_verify["state"],
    "restored_verification": restored_verify["state"],
    "recovered_verification": recovered_verify["state"],
    "restored_audit_pack": restored_audit_pack,
    "recovered_operations": recovery_worker["completed"],
    "post_restore_write": post_restore_write,
    "recovery_point": {
        "boundary": "completed domain writes and durable queued operations before coordinated maintenance checkpoint",
        "outside_boundary": "writes attempted after maintenance begins are rejected or remain outside this backup",
        "claim": "local rehearsal evidence only; no external RPO or zero-RPO claim",
    },
    "timing_seconds": {
        "clock": "host_monotonic",
        "initialization": seconds(initialization_started, initialization_completed),
        "fixture_creation": seconds(fixture_started, fixture_completed),
        "coordinated_backup": seconds(backup_started, backup_completed),
        "backup_inspection": seconds(backup_inspection_started, backup_inspection_completed),
        "restore_plan": seconds(restore_plan_started, restore_plan_completed),
        "restore_apply": seconds(restore_apply_started, restore_apply_completed),
        "post_restore_validation_and_recovery": seconds(
            post_restore_validation_started, post_restore_validation_completed
        ),
        "whole_rehearsal": seconds(rehearsal_started, rehearsal_completed),
        "maintenance_drain": None,
        "maintenance_drain_note": "not separately instrumented; this profile maintenance-gates new claims rather than timing a drain",
    },
    "result": "passed",
}
serialized = json.dumps(result, sort_keys=True)
report_path = sys.argv[15]
if report_path:
    target = Path(report_path)
    if not target.parent.is_dir():
        raise SystemExit("rehearsal report parent directory does not exist")
    with target.open("x", encoding="utf-8") as report:
        report.write(serialized + "\n")
print(serialized)
PY
