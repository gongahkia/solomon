# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from solomon.api.service import IngestRequest, SolomonService
from solomon.backup import create_server_encrypted_backup, inspect_server_encrypted_backup
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.deployment import MaintenanceGate, initialize_deployment

TEST_PASSPHRASE = "subprocess-interruption-passphrase"  # noqa: S105
DATABASE_URL = "postgresql://solomon:subprocess-password@localhost:5432/solomon"


def test_sigkill_during_backup_never_publishes_a_restorable_archive_and_allows_explicit_recovery(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    journal_dir = tmp_path / "journal"
    service = SolomonService(data_dir=data_dir, journal_dir=journal_dir)
    service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="subprocess interruption backup fixture",
            source_kind=SourceKind.PARTNER,
            source_ref="subprocess-interruption",
        )
    )
    initialize_deployment(data_dir=data_dir, journal_dir=journal_dir, database_url=DATABASE_URL)
    archive = tmp_path / "interrupted.enc"
    ready = tmp_path / "dump-started"
    environment = {
        **os.environ,
        "SOLOMON_INTERRUPTION_DATA_DIR": str(data_dir),
        "SOLOMON_INTERRUPTION_JOURNAL_DIR": str(journal_dir),
        "SOLOMON_INTERRUPTION_ARCHIVE": str(archive),
        "SOLOMON_INTERRUPTION_READY": str(ready),
    }
    child = subprocess.Popen(  # noqa: S603 - invokes the current test interpreter with fixed source.
        [
            sys.executable,
            "-c",
            (
                "import os\n"
                "import time\n"
                "from pathlib import Path\n"
                "from solomon.backup import create_server_encrypted_backup\n"
                "def dump(path):\n"
                " Path(os.environ['SOLOMON_INTERRUPTION_READY']).write_text('ready', encoding='utf-8');\n"
                " while True: time.sleep(0.1)\n"
                "create_server_encrypted_backup(\n"
                " data_dir=os.environ['SOLOMON_INTERRUPTION_DATA_DIR'],\n"
                " journal_dir=os.environ['SOLOMON_INTERRUPTION_JOURNAL_DIR'],\n"
                " database_url='postgresql://solomon:subprocess-password@localhost:5432/solomon',\n"
                " destination=os.environ['SOLOMON_INTERRUPTION_ARCHIVE'],\n"
                " passphrase='subprocess-interruption-passphrase', dump_postgres=dump)\n"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "backup subprocess did not enter the PostgreSQL capture boundary"
        child.kill()
        assert child.wait(timeout=10) != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

    assert archive.exists() is False
    assert archive.with_name(f"{archive.name}.manifest.json").exists() is False
    staging = list(tmp_path.glob(".interrupted.enc.incomplete-*"))
    assert len(staging) == 1
    maintenance = MaintenanceGate(data_dir).active()
    assert maintenance is not None

    # SIGKILL deliberately bypasses ordinary cleanup. The archived staging
    # directory is never restorable, while a dead owner can be released only
    # through the explicit persisted operation identifier.
    MaintenanceGate(data_dir).release(maintenance.operation_id)

    def dump_postgres(target: Path) -> None:
        target.write_bytes(b"recovered-postgres-dump")

    retried = create_server_encrypted_backup(
        data_dir=data_dir,
        journal_dir=journal_dir,
        database_url=DATABASE_URL,
        destination=tmp_path / "recovered.enc",
        passphrase=TEST_PASSPHRASE,
        dump_postgres=dump_postgres,
    )

    assert inspect_server_encrypted_backup(retried.archive_path, passphrase=TEST_PASSPHRASE).state == "complete"
    assert MaintenanceGate(data_dir).active() is None
