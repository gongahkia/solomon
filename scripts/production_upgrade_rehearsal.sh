#!/bin/sh
# SPDX-License-Identifier: Apache-2.0

# Proves a bounded N-to-N+1 PostgreSQL operation-store migration with real
# containers. Every resource name includes this process ID and is removed on
# exit; it never targets an operator database, volume, image, or data path.
set -eu

if ! command -v docker >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
    echo "docker and git are required for the production upgrade rehearsal" >&2
    exit 2
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
starting_commit="${SOLOMON_UPGRADE_STARTING_COMMIT:-2d74983b0724ab9f9b4d19a4c8b2bbf0288723ab}"
run_id="solomon-upgrade-$$"
network="${run_id}-network"
postgres="${run_id}-postgres"
restore_postgres="${run_id}-restore-postgres"
old_image="${run_id}-old-image"
current_image="${run_id}-current-image"
work="$(mktemp -d "${TMPDIR:-/tmp}/solomon-upgrade.XXXXXX")"
old_root="$work/old"
state="$work/state"
report_path="${SOLOMON_UPGRADE_REPORT_PATH:-}"
if [ -n "$report_path" ] && [ -e "$report_path" ]; then
    echo "upgrade rehearsal report path must not already exist" >&2
    exit 2
fi

cleanup() {
    status=$?
    docker rm --force "$postgres" "$restore_postgres" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker run --rm -v "$work:/state" --entrypoint /bin/sh "$current_image" \
        -c 'find /state -mindepth 1 -delete' >/dev/null 2>&1 || true
    rmdir "$work" >/dev/null 2>&1 || true
    docker image rm "$old_image" "$current_image" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

mkdir "$old_root" "$state"
chmod 0777 "$state"
git -C "$root" archive "$starting_commit" | tar -x -C "$old_root"
docker build --quiet -t "$old_image" "$old_root" >/dev/null
docker build --quiet -t "$current_image" "$root" >/dev/null
docker network create "$network" >/dev/null
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

for name in "$postgres" "$restore_postgres"; do
    docker run --detach --rm --name "$name" --network "$network" \
        -e POSTGRES_DB=solomon \
        -e POSTGRES_USER=solomon \
        -e POSTGRES_PASSWORD=disposable-postgres-password \
        pgvector/pgvector:0.8.2-pg16-bookworm >/dev/null
    wait_for_postgres "$name"
done

database_url="postgresql://solomon:disposable-postgres-password@${postgres}:5432/solomon"
restore_database_url="postgresql://solomon:disposable-postgres-password@${restore_postgres}:5432/solomon"

run_image() {
    image="$1"
    shift
    timeout 120 docker run --rm --network "$network" -v "$state:/state" \
        -v "$root/examples:/app/examples:ro" \
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$database_url" \
        -e SOLOMON_DATA_DIR=/state/data \
        -e SOLOMON_JOURNAL_DIR=/state/journal \
        -e SOLOMON_BACKUP_PASSPHRASE=disposable-backup-passphrase \
        "$image" "$@"
}

run_restore_control() {
    timeout 120 docker run --rm --network "$network" -v "$state:/state" \
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$restore_database_url" \
        -e SOLOMON_RESTORE_DATABASE_URL="$restore_database_url" \
        -e SOLOMON_DATA_DIR=/tmp/restore-control-data \
        -e SOLOMON_JOURNAL_DIR=/tmp/restore-control-journal \
        -e SOLOMON_BACKUP_PASSPHRASE=disposable-backup-passphrase \
        "$current_image" "$@"
}

run_restored_old() {
    timeout 120 docker run --rm --network "$network" -v "$state:/state" \
        -e SOLOMON_SKU=server \
        -e SOLOMON_SERVER_AUTH_MODE=legacy-api-key \
        -e SOLOMON_SERVER_API_KEY=disposable-server-key \
        -e SOLOMON_DATABASE_URL="$restore_database_url" \
        -e SOLOMON_DATA_DIR=/state/pre-upgrade-restored/data \
        -e SOLOMON_JOURNAL_DIR=/state/pre-upgrade-restored/journal \
        "$old_image" "$@"
}

run_image "$old_image" solomon migrate >/dev/null
run_image "$old_image" python /app/examples/scenarios/governed-dependency-assertion-proof/run.py \
    --workspace /state/old-fixture \
    --data-dir /state/data \
    --journal-dir /state/journal \
    --database-url "$database_url" \
    --audit-pack-dir /state/data/pre-upgrade-audit-pack \
    --serial-confirmation > "$work/old-fixture.json"
run_image "$current_image" solomon deployment init --owner upgrade-rehearsal >/dev/null
run_image "$current_image" solomon deployment upgrade-preflight --format json >/dev/null
run_image "$current_image" solomon deployment backup /state/pre-upgrade.enc >/dev/null
run_image "$current_image" solomon deployment backup-inspect /state/pre-upgrade.enc >/dev/null
run_restore_control solomon deployment restore-plan /state/pre-upgrade.enc /state/pre-upgrade-restored \
    --output /state/pre-upgrade-restore-plan.json >/dev/null
restore_tables="$(docker exec "$restore_postgres" psql -U solomon -d solomon -Atc \
    "SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_schema <> 'information_schema' AND table_schema NOT LIKE 'pg_%' AND table_type = 'BASE TABLE' ORDER BY 1")"
if [ -n "$restore_tables" ]; then
    echo "isolated pre-upgrade restore target contains application tables" >&2
    exit 1
fi
run_restore_control solomon deployment restore --plan /state/pre-upgrade-restore-plan.json --apply >/dev/null
run_restored_old solomon health > "$work/pre-upgrade-old-health.json"
run_image "$current_image" solomon migrate >/dev/null
run_image "$current_image" python /app/examples/scenarios/governed-dependency-assertion-proof/run.py \
    --workspace /state/post-upgrade-proof \
    --data-dir /state/data \
    --journal-dir /state/journal \
    --database-url "$database_url" \
    --post-restore-write > "$work/post-upgrade-write.json"
run_image "$current_image" solomon health > "$work/health.json"
run_image "$current_image" solomon deployment backup /state/post-upgrade.enc >/dev/null
run_image "$current_image" solomon deployment backup-inspect /state/post-upgrade.enc >/dev/null

migrations="$(docker exec "$postgres" psql -U solomon -d solomon -Atc \
    "SELECT version FROM schema_migrations WHERE scope = 'operation-store' ORDER BY version")"
if [ "$migrations" != "1
2" ]; then
    echo "N-to-N+1 operation-store migration did not reach versions 1 and 2" >&2
    exit 1
fi
if run_image "$old_image" solomon health >/dev/null 2>&1; then
    echo "older application unexpectedly accepted the N+1 operation-store schema" >&2
    exit 1
fi

python - "$work/health.json" "$work/pre-upgrade-old-health.json" "$work/old-fixture.json" "$work/post-upgrade-write.json" "$report_path" <<'PY'
import json
import sys
from pathlib import Path

health = json.load(open(sys.argv[1], encoding="utf-8"))
pre_upgrade_old = json.load(open(sys.argv[2], encoding="utf-8"))
old_fixture = json.load(open(sys.argv[3], encoding="utf-8"))
post_upgrade_write = json.load(open(sys.argv[4], encoding="utf-8"))
if health["store"]["item_count"] != 5:
    raise SystemExit("post-upgrade knowledge inventory differs from expected N and N+1 writes")
if not health["journal"]["ok"]:
    raise SystemExit("post-upgrade audit journal failed verification")
if pre_upgrade_old["store"]["item_count"] != 4 or not pre_upgrade_old["journal"]["ok"]:
    raise SystemExit("verified pre-upgrade backup was not readable by the previous application")
if old_fixture["decisions"] != {"confirmed": 1, "deferred": 1, "rejected": 1, "withdrawn": 1}:
    raise SystemExit("N fixture did not preserve governed assertion lifecycle coverage")
if post_upgrade_write["result"] != "passed" or not post_upgrade_write["edge_provenance_matches"]:
    raise SystemExit("post-upgrade governed write did not retain edge provenance")
result = {
    "schema_id": "solomon.production_upgrade_rehearsal.v2",
    "operation_store_migrations": [1, 2],
    "pre_upgrade_backup_restore": "previous-binary-readable",
    "governed_fixture": old_fixture,
    "post_upgrade_backup": "verified",
    "rollback": "refused-by-older-binary",
    "post_upgrade_write": post_upgrade_write,
    "result": "passed",
}
serialized = json.dumps(result, sort_keys=True)
report_path = sys.argv[5]
if report_path:
    target = Path(report_path)
    if not target.parent.is_dir():
        raise SystemExit("upgrade rehearsal report parent directory does not exist")
    with target.open("x", encoding="utf-8") as report:
        report.write(serialized + "\n")
print(serialized)
PY
