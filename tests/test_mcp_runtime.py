# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import hashlib
import json
import string
import tempfile
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from solomon.api.service import AuthorityChangeRequest, DependencyRequest, IngestRequest, SolomonService
from solomon.boundary.solomon import SolomonBoundary
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType
from solomon.mcp.rate_limit import TokenBucketConfig, TokenBucketRateLimiter
from solomon.mcp.tools import SolomonMCPRuntime

SAFE_TEXT = st.text(alphabet=string.ascii_letters + string.digits + " _.,;:-", min_size=1, max_size=60)
LARGE_PASTED_TEXT = st.text(
    alphabet=string.ascii_letters + string.digits + " \n\t.,;:-",
    min_size=2048,
    max_size=4096,
)
UNICODE_EDGE_TEXT = st.text(
    alphabet=string.ascii_letters + string.digits + " \t\n" + "\u202e\ufeff\u2066\u200d\u00a0",
    min_size=1,
    max_size=120,
).map(lambda text: f"\u202e\ufeff{text}\u2066")
BASE64_BLOB_TEXT = st.binary(min_size=256, max_size=1024).map(lambda blob: base64.b64encode(blob).decode("ascii"))
BOUNDARY_FUZZ_TEXT = st.one_of(LARGE_PASTED_TEXT, UNICODE_EDGE_TEXT, BASE64_BLOB_TEXT)
MCP_CURRENCY_STATES = {
    "Live": "live",
    "StalePendingReverification": "stale_pending",
    "Superseded": "superseded",
    "Retired": "retired",
}


def test_mcp_runtime_maps_all_required_tools_to_service(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    runtime = SolomonMCPRuntime(service)

    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x depends on regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    successor = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="updated structure x view",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-2",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    other_item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="other matter also depends on regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-other",
            matter_id="matter-b",
            client_id="client-b",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=other_item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )

    health = runtime.health(caller_id="claude:test")
    assert health["version"]
    assert health["store"]["item_count"] == 3
    assert health["journal"]["ok"] is True
    assert health["boundary"]["importable"] is True

    preflight = runtime.preflight_context(query="structure x", matter_id="matter-a", client_id="client-a")
    assert preflight["items"][0]["item"]["id"] in {item.id, successor.id}

    currency = runtime.check_currency(knowledge_item_id=item.id)
    assert currency["knowledge_item_id"] == item.id
    assert currency["state"] == "live"

    denied = runtime.check_currency(knowledge_item_id=item.id, matter_id="matter-b", client_id="client-b")
    assert denied["ok"] is False
    assert denied["error"]["code"] == "scope_denied"

    dependencies = runtime.get_dependencies(knowledge_item_id=item.id)
    assert dependencies["upstream"][0]["target_id"] == "reg-r-12"

    suggestions = runtime.dependency_suggestions(knowledge_item_id=item.id)
    assert "suggestions" in suggestions

    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="v2", changed_at="2026-01-01T00:00:00+00:00"),
    )
    queue = runtime.verification_queue(matter_id="matter-a", client_id="client-a")
    assert queue["items"][0]["item"]["id"] == item.id
    assert queue["items"][0]["latest_event"]["state"] == "verification_requested"

    impact = runtime.impact(external_authority_id="reg-r-12", matter_id="matter-a", client_id="client-a")
    assert item.id in impact["stale_item_ids"]
    assert other_item.id not in impact["stale_item_ids"]

    verification = runtime.verify_position(
        knowledge_item_id=item.id,
        verifier_id="partner-a",
        decision="supersede",
        evidence_ref="memo-2",
        successor_id=successor.id,
    )
    assert verification["item"]["successor_id"] == successor.id
    assert verification["currency"]["state"] == "superseded"

    ingested = runtime.ingest(
        text="new clause depends on regulation r section 12",
        source_ref="memo-3",
        scope={"matter_id": "matter-a", "client_id": "client-a"},
        kind="clause",
        source_kind="associate",
    )
    assert ingested["item"]["kind"] == "clause"

    audit_pack = runtime.audit_pack(knowledge_item_id=item.id)
    assert audit_pack["knowledge_item_id"] == item.id
    assert audit_pack["format"] == "json"
    assert "manifest_json" in audit_pack["pack"]


def test_mcp_preflight_rejects_boundary_unsafe_output(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
        )
    )
    service.boundary = SolomonBoundary(HighRiskBoundaryClient())
    runtime = SolomonMCPRuntime(service)

    result = runtime.preflight_context(query=item.content)

    assert result["ok"] is False
    assert result["error"]["code"] == "boundary_rejected"
    assert result["error"]["details"]["classification"] == "HIGH_RISK"


def test_mcp_ingest_rejects_boundary_unsafe_output(tmp_path: Path) -> None:
    client = RecordingHighRiskBoundaryClient()
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    service.boundary = SolomonBoundary(client)
    runtime = SolomonMCPRuntime(service)

    result = runtime.ingest(
        text="boundary blocked item",
        source_ref="memo-unsafe",
        scope={"matter_id": "matter-a", "client_id": "client-a"},
        kind="position",
        source_kind="partner",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "boundary_rejected"
    assert client.review_requests[-1]["document_type"] == "mcp_tool_result"


def test_mcp_item_scoped_tools_deny_wrong_scope(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    runtime = SolomonMCPRuntime(service)

    results = [
        runtime.check_currency(knowledge_item_id=item.id, matter_id="matter-b", client_id="client-b"),
        runtime.get_dependencies(knowledge_item_id=item.id, matter_id="matter-b", client_id="client-b"),
        runtime.verify_position(
            knowledge_item_id=item.id,
            verifier_id="partner-a",
            decision="reaffirm",
            evidence_ref="memo-1",
            matter_id="matter-b",
            client_id="client-b",
        ),
        runtime.audit_pack(knowledge_item_id=item.id, matter_id="matter-b", client_id="client-b"),
        runtime.dependency_suggestions(knowledge_item_id=item.id, matter_id="matter-b", client_id="client-b"),
    ]

    assert {result["error"]["code"] for result in results} == {"scope_denied"}


def test_mcp_impact_stale_propagation_updates_currency(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x depends on regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    runtime = SolomonMCPRuntime(service)

    impact = runtime.impact(external_authority_id="reg-r-12", matter_id="matter-a", client_id="client-a")
    service.register_authority_change(
        "reg-r-12",
        AuthorityChangeRequest(new_version="v2", changed_at="2026-01-01T00:00:00+00:00"),
    )
    currency = runtime.check_currency(knowledge_item_id=item.id, matter_id="matter-a", client_id="client-a")

    assert impact["stale_item_ids"] == [item.id]
    assert currency["state"] == "stale_pending"
    assert currency["reasons"]


def test_mcp_audit_pack_contains_verifiable_manifest(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    runtime = SolomonMCPRuntime(service)

    pack = runtime.audit_pack(knowledge_item_id=item.id, matter_id="matter-a", client_id="client-a")
    manifest = json.loads(pack["pack"]["manifest_json"])
    unsigned_manifest = dict(manifest)
    supplied_hash = unsigned_manifest.pop("manifest_sha256")
    computed_hash = hashlib.sha256(
        json.dumps(unsigned_manifest, sort_keys=True, indent=2).encode("utf-8")
    ).hexdigest()

    assert manifest["schema"] == "solomon.audit_pack.v1"
    assert manifest["journal_file"] == "journal.jsonl"
    assert manifest["journal_sha256"]
    assert supplied_hash == computed_hash
    assert pack["hash_chain"]["entry_hash"]


def test_mcp_call_logging_records_required_fields(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            matter_id="matter-a",
            client_id="client-a",
        )
    )
    runtime = SolomonMCPRuntime(service)

    runtime.check_currency(
        knowledge_item_id=item.id,
        matter_id="matter-a",
        client_id="client-a",
        caller_id="claude:test",
    )

    entries = [
        json.loads(line)
        for line in (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    mcp_entries = [entry for entry in entries if entry["event_type"] == "mcp_call"]
    payload = mcp_entries[-1]["payload"]
    assert payload["tool_name"] == "solomon.check_currency"
    assert payload["caller_id"] == "claude:test"
    assert payload["matter_id"] == "matter-a"
    assert payload["client_id"] == "client-a"
    assert payload["currency_outcome"] == "live"
    assert payload["boundary_outcome"] is None
    assert payload["input_sha256"]


def test_mcp_runtime_rate_limits_per_caller(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="structure x under regulation r section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
        )
    )
    limiter = TokenBucketRateLimiter(TokenBucketConfig(capacity=1, refill_per_second=0.0))
    runtime = SolomonMCPRuntime(service, rate_limiter=limiter)

    first = runtime.check_currency(knowledge_item_id=item.id, caller_id="caller-a")
    second = runtime.check_currency(knowledge_item_id=item.id, caller_id="caller-a")
    other = runtime.check_currency(knowledge_item_id=item.id, caller_id="caller-b")

    assert first["state"] == "live"
    assert second["ok"] is False
    assert second["error"]["code"] == "rate_limited"
    assert other["state"] == "live"


@given(contents=st.lists(SAFE_TEXT, min_size=1, max_size=6), supersede_count=st.integers(min_value=0, max_value=5))
@settings(deadline=None, max_examples=20)
def test_mcp_check_currency_matches_internal_engine_property(contents: list[str], supersede_count: int) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-mcp-currency-") as tmp:
        root = Path(tmp)
        service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
        runtime = SolomonMCPRuntime(service)
        items = [
            service.ingest(
                IngestRequest(
                    kind=KnowledgeKind.POSITION,
                    content=f"property position {index}: {content}",
                    source_kind=SourceKind.PARTNER,
                    source_ref=f"memo-{index}",
                    matter_id="matter-a",
                    client_id="client-a",
                )
            )
            for index, content in enumerate(contents)
        ]

        for index in range(min(supersede_count, len(items) - 1)):
            runtime.verify_position(
                knowledge_item_id=items[index].id,
                verifier_id="partner-a",
                decision="supersede",
                evidence_ref=f"memo-{index + 1}",
                successor_id=items[index + 1].id,
                matter_id="matter-a",
                client_id="client-a",
            )

        for item in items:
            internal = service.evaluate_currency(item.id)
            mcp = runtime.check_currency(
                knowledge_item_id=item.id,
                matter_id="matter-a",
                client_id="client-a",
            )
            assert mcp["state"] == MCP_CURRENCY_STATES[str(internal["currency_state"])]
            assert mcp["successor_id"] == service.store.get_item(item.id).successor_id


@given(payload=BOUNDARY_FUZZ_TEXT)
@settings(deadline=None, max_examples=12)
def test_mcp_preflight_boundary_fuzz_rejects_unsafe_output(payload: str) -> None:
    with tempfile.TemporaryDirectory(prefix="solomon-mcp-boundary-") as tmp:
        root = Path(tmp)
        client = RecordingHighRiskBoundaryClient()
        service = SolomonService(data_dir=root / "data", journal_dir=root / "journal")
        service.boundary = SolomonBoundary(client)
        service.ingest(
            IngestRequest(
                kind=KnowledgeKind.POSITION,
                content=f"boundary fuzz payload {payload}",
                source_kind=SourceKind.PARTNER,
                source_ref="fuzz",
                matter_id="matter-a",
                client_id="client-a",
            )
        )
        runtime = SolomonMCPRuntime(service)

        result = runtime.preflight_context(query="boundary fuzz payload", matter_id="matter-a", client_id="client-a")

        assert result["ok"] is False
        assert result["error"]["code"] == "boundary_rejected"
        assert result["error"]["details"]["classification"] == "HIGH_RISK"
        assert "items" not in result
        assert client.review_requests[-1]["document_type"] == "mcp_tool_result"
        assert "boundary fuzz payload" in client.review_requests[-1]["text"]


class RecordingHighRiskBoundaryClient:
    def __init__(self) -> None:
        self.review_requests: list[dict[str, Any]] = []

    def review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.review_requests.append(dict(kwargs["request"]))
        return {"classification": "HIGH_RISK", "findings": [{"kind": "fuzz"}]}

    def pseudonymize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"pseudonymized_text": kwargs["request"]["text"], "mapping": []}

    def reidentify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"reidentified_text": ""}

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}


class HighRiskBoundaryClient:
    def review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"classification": "HIGH_RISK", "findings": [{"kind": "mnpi_or_high_risk_secret"}]}

    def pseudonymize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"pseudonymized_text": "", "mapping": []}

    def reidentify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"reidentified_text": ""}

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}
