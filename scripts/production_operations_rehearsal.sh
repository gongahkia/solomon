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
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$restore_url" \
        -e SOLOMON_DATA_DIR=/state/restored/data \
        -e SOLOMON_JOURNAL_DIR=/state/restored/journal \
        "$image" "$@"
}

source_run solomon migrate >/dev/null
source_run solomon deployment init --owner rehearsal >/dev/null
source_run solomon deployment preflight --require-initialized --format json >/dev/null
source_run solomon ingest "rehearsal source position under Regulation R section 12" --source-ref rehearsal-source >/dev/null
source_run solomon deployment backup /state/checkpoint.enc >/dev/null
source_run solomon deployment backup-inspect /state/checkpoint.enc >/dev/null
source_run solomon health > "$work/source-health.json"

restore_run solomon deployment restore-plan /state/checkpoint.enc /state/restored --output /state/restore-plan.json >/dev/null
restore_tables="$(docker exec "$restore_pg" psql -U solomon -d solomon -Atc \
    "SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_schema <> 'information_schema' AND table_schema NOT LIKE 'pg_%' AND table_type = 'BASE TABLE' ORDER BY 1")"
if [ -n "$restore_tables" ]; then
    echo "restore target contains application tables before restore" >&2
    printf '%s\n' "$restore_tables" >&2
    exit 1
fi
restore_run solomon deployment restore --plan /state/restore-plan.json --apply >/dev/null
restored_run solomon deployment preflight --require-initialized --format json >/dev/null
restored_run solomon health > "$work/restored-health.json"
restored_run solomon ingest "post-restore write under Regulation R section 13" --source-ref rehearsal-restored >/dev/null

python - "$work/source-health.json" "$work/restored-health.json" <<'PY'
import json
import sys

source = json.load(open(sys.argv[1], encoding="utf-8"))
restored = json.load(open(sys.argv[2], encoding="utf-8"))
if source["store"]["item_count"] != restored["store"]["item_count"]:
    raise SystemExit("restored knowledge inventory differs from checkpoint")
if not source["journal"]["ok"] or not restored["journal"]["ok"]:
    raise SystemExit("source or restored audit journal failed verification")
print(json.dumps({
    "schema_id": "solomon.production_operations_rehearsal.v1",
    "profile": "mixed-postgresql-sqlite",
    "source_item_count": source["store"]["item_count"],
    "restored_item_count": restored["store"]["item_count"],
    "source_audit_entries": source["journal"]["entries"],
    "restored_audit_entries": restored["journal"]["entries"],
    "post_restore_write": "succeeded",
    "result": "passed",
}, sort_keys=True))
PY
