# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from solomon.audit.journal import AuditAttribution, AuditJournal


def test_audit_attribution_is_hash_chained_and_filterable(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = AuditJournal(path)
    attribution = AuditAttribution(
        actor_id="lawyer-a",
        correlation_id="request-1",
        source_connector_id="official-gazette",
        review_task_id="task-1",
    )
    journal.append("review_task_resolved", {"decision": "reaffirm"}, attribution=attribution)
    journal.append("other", {}, attribution=AuditAttribution(actor_id="lawyer-b", correlation_id="request-2"))

    entry = journal.list_entries(correlation_id="request-1", actor_id="lawyer-a")[0]
    assert entry.attribution == attribution
    assert journal.verify().ok is True

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["attribution"]["actor_id"] = "lawyer-b"
    path.write_text(json.dumps(tampered) + "\n" + lines[1] + "\n", encoding="utf-8")
    assert journal.verify().ok is False


def test_audit_attribution_rejects_empty_identity_values():
    with pytest.raises(ValidationError):
        AuditAttribution(actor_id="")
