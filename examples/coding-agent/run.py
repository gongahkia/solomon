#!/usr/bin/env python3
"""Minimal coding-agent memory demo.

This is intentionally deterministic: it exercises memory behavior without
calling an LLM so the example can run in CI and during portfolio demos.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY_BINDING = ROOT / "bindings" / "python" / "python"
sys.path.insert(0, str(ROOT))
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))

from benchmarks.shibahama_bench.embeddings import embed_text


@dataclass(frozen=True)
class Observation:
    content: str
    source_ref: str
    valid_from_unix: int
    supersedes_source_ref: str | None = None


class ShibahamaMemory:
    name = "shibahama"

    def __init__(self, path: Path) -> None:
        import shibahama

        self.engine = shibahama.Shibahama(str(path), 16)
        self.ids_by_source_ref: dict[str, str] = {}

    def ingest(self, observation: Observation) -> None:
        if observation.supersedes_source_ref:
            superseded = self.ids_by_source_ref.get(observation.supersedes_source_ref)
            if superseded:
                self.engine.invalidate(superseded, observation.valid_from_unix)

        item = self.engine.write(
            observation.content,
            vector=embed_text(observation.content),
            source_kind="user",
            source_ref=observation.source_ref,
            ingested_by="coding-agent-demo",
            valid_from_unix=observation.valid_from_unix,
            ingested_at_unix=observation.valid_from_unix,
        )
        self.ids_by_source_ref[observation.source_ref] = item.id

    def recall(self, prompt: str, now_unix: int) -> str:
        candidates = self.engine.recall(
            embed_text(prompt),
            3,
            now_unix=now_unix,
            raw_query_context=prompt,
            include_cold=True,
        )

        return "\n".join(candidate.item.content for candidate in candidates)

    def recording(self) -> dict[str, object]:
        memories = [
            {
                "id": item.provenance.source_ref or item.id,
                "content": item.content,
                "tier": item.tier,
                "credence": item.credence,
                "significance": item.significance,
                "valid_from_unix": item.valid_from_unix,
                "valid_to_unix": item.valid_to_unix,
            }
            for item in sorted(
                self.engine.memory_items(),
                key=lambda value: (value.valid_from_unix, value.provenance.source_ref or value.id),
            )
        ]
        return {
            "schema_version": 1,
            "namespace": "coding-agent-demo",
            "memory_count": len(memories),
            "memories": memories,
            "events": [
                {
                    "sequence": index + 1,
                    "kind": "demo_step",
                    "memory_ids": [memory["id"]],
                    "recorded_at_unix": memory["valid_from_unix"],
                }
                for index, memory in enumerate(memories)
            ],
        }


class WarehouseMemory:
    name = "warehouse"

    def __init__(self) -> None:
        self.rows: list[Observation] = []

    def ingest(self, observation: Observation) -> None:
        self.rows.append(observation)

    def recall(self, prompt: str, now_unix: int) -> str:
        prompt_terms = set(prompt.casefold().replace("/", " ").split())
        scored = []
        for index, row in enumerate(self.rows):
            row_terms = set(row.content.casefold().replace("/", " ").split())
            scored.append((len(prompt_terms & row_terms), index, row.content))
        scored.sort(reverse=True)
        return "\n".join(content for overlap, _, content in scored[:3] if overlap > 0)


class CodingAgent:
    def __init__(self, memory) -> None:
        self.memory = memory

    def storage_strategy(self) -> str:
        context = self.memory.recall("Should tests use a global singleton store?", 500)
        if "Backlog idea from an old review" in context:
            return "Add a global singleton store for test convenience."
        if "do not add a global singleton store" in context.casefold():
            return "Use per-test temporary stores; do not add a global singleton store."
        return "Add a global singleton store for test convenience."

    def ranking_file(self) -> str:
        context = self.memory.recall("Which file owns recall ranking changes?", 500)
        if "File location: recall ranking changes live in core/src/rank.rs." in context:
            return "Edit core/src/rank.rs."
        if "core/src/retrieval.rs" in context and "core/src/rank.rs was removed" in context:
            return "Re-validate the move, then edit core/src/retrieval.rs."
        return "Search the repository before citing a path."


def seed(memory) -> None:
    observations = [
        Observation(
            "Rejected approach: do not add a global singleton store; tests need isolated stores.",
            "decision:singleton-rejected",
            0,
        ),
        Observation(
            "Backlog idea from an old review: add a global singleton store for test convenience.",
            "idea:singleton-old",
            30,
        ),
        Observation(
            "Decision reaffirmed: do not add a global singleton store; use per-test temp stores.",
            "decision:singleton-current",
            90,
            supersedes_source_ref="idea:singleton-old",
        ),
        Observation(
            "File location: recall ranking changes live in core/src/rank.rs.",
            "file:rank-old",
            60,
        ),
        Observation(
            "File move: core/src/retrieval.rs now owns recall ranking; core/src/rank.rs was removed.",
            "file:rank-current",
            120,
            supersedes_source_ref="file:rank-old",
        ),
    ]
    for observation in observations:
        memory.ingest(observation)


def run_system(memory) -> dict[str, object]:
    seed(memory)
    agent = CodingAgent(memory)
    storage = agent.storage_strategy()
    ranking = agent.ranking_file()
    return {
        "system": memory.name,
        "scenario_a": {
            "answer": storage,
            "passed": "do not add a global singleton store" in storage.casefold(),
        },
        "scenario_b": {
            "answer": ranking,
            "passed": "core/src/retrieval.rs" in ranking and "re-validate" in ranking.casefold(),
        },
    }


def main() -> int:
    output_dir = Path(__file__).resolve().parent / "out"
    output_dir.mkdir(exist_ok=True)
    tmpdir = tempfile.TemporaryDirectory()
    shibahama_memory = ShibahamaMemory(Path(tmpdir.name) / "agent.redb")
    warehouse_memory = WarehouseMemory()
    results = [run_system(shibahama_memory), run_system(warehouse_memory)]
    recording = shibahama_memory.recording()

    (output_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (output_dir / "tideline-recording.json").write_text(
        json.dumps(recording, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(results, indent=2))

    shibahama_result = results[0]
    warehouse_result = results[1]
    assert shibahama_result["scenario_a"]["passed"]
    assert shibahama_result["scenario_b"]["passed"]
    assert not warehouse_result["scenario_a"]["passed"]
    assert not warehouse_result["scenario_b"]["passed"]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
