# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from solomon.api.service import RecallRequest
from solomon.currency.engine import evaluate_currency
from solomon.currency.models import CurrencyState
from solomon.orchestrator.retrieval import tokenize
from solomon.sources.models import CandidateClaimStatus

if TYPE_CHECKING:
    from solomon.mcp.tools.runtime import SolomonMCPRuntime


def preflight_candidates(
    runtime: SolomonMCPRuntime,
    *,
    query: str,
    matter_id: str | None,
    client_id: str | None,
    max_items: int,
    max_context_tokens: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str | None]]]:
    results = runtime.service.recall(
        RecallRequest(
            query=query,
            matter_id=matter_id,
            client_id=client_id,
            review_mode=False,
            limit=max_items,
            max_context_tokens=max_context_tokens,
        )
    )
    exclusions = _matching_item_exclusions(
        runtime,
        query=query,
        matter_id=matter_id,
        client_id=client_id,
        max_items=max_items,
    )
    exclusions.extend(_unpromoted_claim_exclusions(runtime, query=query))
    return results, exclusions


def boundary_rejections(results: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    exclusions: list[dict[str, str | None]] = []
    for result in results:
        item = result.get("item")
        item_id = item.get("id") if isinstance(item, dict) else None
        exclusions.append(
            {
                "item_id": item_id if isinstance(item_id, str) else None,
                "candidate_id": None,
                "code": "boundary_rejected",
                "reason": "candidate withheld by output boundary review",
            }
        )
    return exclusions


def rejected_boundary_metadata(review: dict[str, Any]) -> dict[str, Any]:
    error = review.get("error")
    details = error.get("details") if isinstance(error, dict) else {}
    return {
        "status": "rejected",
        "classification": details.get("classification") if isinstance(details, dict) else None,
        "finding_count": details.get("finding_count", 0) if isinstance(details, dict) else 0,
        "context_id": None,
    }


def _matching_item_exclusions(
    runtime: SolomonMCPRuntime,
    *,
    query: str,
    matter_id: str | None,
    client_id: str | None,
    max_items: int,
) -> list[dict[str, str | None]]:
    hits = runtime.service.index.search(query, limit=max(max_items * 4, max_items))
    items = {item.id: item for item in runtime.service.store.get_many(hit.item_id for hit in hits)}
    exclusions: list[dict[str, str | None]] = []
    for hit in hits:
        item = items.get(hit.item_id)
        if item is None:
            continue
        if _outside_scope(item.matter_id, item.client_id, matter_id=matter_id, client_id=client_id):
            exclusions.append(
                {
                    "item_id": None,
                    "candidate_id": None,
                    "code": "unauthorized",
                    "reason": "matching candidate is outside the requested scope",
                }
            )
        elif evaluate_currency(item).currency_state is not CurrencyState.LIVE:
            exclusions.append(
                {
                    "item_id": item.id,
                    "candidate_id": None,
                    "code": "stale",
                    "reason": "matching candidate is not current",
                }
            )
    return exclusions


def _unpromoted_claim_exclusions(runtime: SolomonMCPRuntime, *, query: str) -> list[dict[str, str | None]]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    exclusions: list[dict[str, str | None]] = []
    for source in runtime.service.document_store.list_sources():
        for document in runtime.service.document_store.list_documents(source.id):
            for candidate in runtime.service.document_store.list_candidates(
                document.id,
                status=CandidateClaimStatus.PENDING,
            ):
                if query_tokens.isdisjoint(tokenize(candidate.content)):
                    continue
                exclusions.append(
                    {
                        "item_id": None,
                        "candidate_id": candidate.id,
                        "code": "unpromoted",
                        "reason": "matching candidate claim is awaiting promotion",
                    }
                )
    return exclusions


def _outside_scope(
    item_matter_id: str | None,
    item_client_id: str | None,
    *,
    matter_id: str | None,
    client_id: str | None,
) -> bool:
    return (matter_id is not None and item_matter_id != matter_id) or (
        client_id is not None and item_client_id != client_id
    )
