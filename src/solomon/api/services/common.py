# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from solomon.api.schemas import SolomonModel
from solomon.api.service_models import PrimitivePlanExecution


def build_answer_prompt(query: str, recalled: list[dict[str, Any]]) -> str:
    context_blocks: list[str] = []
    for index, entry in enumerate(recalled, start=1):
        item = entry["item"]
        provenance = entry["provenance"]
        context_blocks.append(
            "\n".join(
                [
                    f"[{index}] item_id={item['id']}",
                    f"currency={entry['currency_state']} credence={item['credence_tier']}",
                    f"source={provenance['source_ref']} source_kind={provenance['source_kind']}",
                    f"stale_reasons={entry['stale_reasons']}",
                    item["content"],
                ]
            )
        )
    context = "\n\n".join(context_blocks) if context_blocks else "No live Solomon context was recalled."
    return "\n".join(
        [
            "You are answering from Solomon's recalled firm knowledge.",
            "Use only the recalled context. If context is missing or stale, say so.",
            f"Question: {query}",
            "Recalled context:",
            context,
        ]
    )


def parse_iso_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def jsonable(value: Any) -> Any:
    if isinstance(value, SolomonModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [jsonable(entry) for entry in value]
    if isinstance(value, dict):
        return {str(key): jsonable(entry) for key, entry in value.items()}
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def result_summary(value: Any) -> dict[str, Any]:
    identifiers: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key in ("id", "item_id", "authority_id", "changed_dependency_id"):
                raw = current.get(key)
                if isinstance(raw, str):
                    identifiers.add(f"{key}:{raw}")
            for nested in current.values():
                walk(nested)
        elif isinstance(current, list):
            for nested in current:
                walk(nested)

    walk(value)
    summary: dict[str, Any] = {"result_type": type(value).__name__, "identifiers": sorted(identifiers)}
    if isinstance(value, list):
        summary["count"] = len(value)
    elif isinstance(value, dict):
        summary["keys"] = sorted(value)
    return summary


def plan_explainability_summary(execution: PrimitivePlanExecution) -> dict[str, Any]:
    return {
        "plan_id": execution.plan_id,
        "schema_id": execution.schema_id,
        "plan": execution.plan.model_dump(mode="json"),
        "store_state_sha256": execution.store_state_sha256,
        "audit_event_hash": execution.audit_event_hash,
        "steps": [
            {
                "index": step.index,
                "primitive": step.primitive,
                "args_sha256": step.args_sha256,
                "result_sha256": step.result_sha256,
                "result_summary": step.result_summary,
            }
            for step in execution.steps
        ],
    }
