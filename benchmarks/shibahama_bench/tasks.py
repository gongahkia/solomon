"""Benchmark task definitions and suite loaders."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Observation:
    """One memory observation supplied to a system."""

    content: str
    valid_from_unix: int
    source_ref: str
    supersedes_source_ref: str | None = None


@dataclass(frozen=True)
class BenchmarkQuery:
    """One retrieval question and expected evidence."""

    prompt: str
    expected: str
    forbidden: str | None = None
    now_unix: int = 0
    changed_at_unix: int | None = None


@dataclass(frozen=True)
class BenchmarkCase:
    """A complete memory benchmark scenario."""

    name: str
    observations: tuple[Observation, ...]
    queries: tuple[BenchmarkQuery, ...]
    metadata: dict[str, str]


def load_suite(name: str, dataset: Path | None = None, seed: int = 7) -> list[BenchmarkCase]:
    """Load a named suite."""

    if name == "currencybench":
        return currencybench(seed)
    if name == "coding-agent":
        return coding_agent_memory_task(seed)
    if name in {"locomo", "longmemeval"}:
        if dataset is None:
            raise ValueError(f"{name} requires --dataset JSONL")
        return load_jsonl_suite(dataset, suite_name=name)

    raise ValueError(f"unknown suite: {name}")


def currencybench(seed: int = 7) -> list[BenchmarkCase]:
    """Return deterministic fact-change cases for stale-answer measurement."""

    rng = random.Random(seed)
    cases = [
        (
            "billing-owner",
            "Billing ownership moved from Maya to Jules",
            "The billing service owner is Maya.",
            "The billing service owner is Jules.",
            "Who owns the billing service?",
            "Jules",
            "Maya",
        ),
        (
            "api-route",
            "API route moved from v1 to v2",
            "The user lookup endpoint is /api/v1/users/{id}.",
            "The user lookup endpoint is /api/v2/users/{id}.",
            "What is the current user lookup endpoint?",
            "/api/v2/users/{id}",
            "/api/v1/users/{id}",
        ),
        (
            "deploy-region",
            "Deploy region changed after latency incident",
            "The production region is us-east-1.",
            "The production region is us-west-2.",
            "Which production region is current?",
            "us-west-2",
            "us-east-1",
        ),
        (
            "feature-flag",
            "Feature flag renamed after rollout",
            "The checkout kill switch is checkout_disable_all.",
            "The checkout kill switch is checkout_halt_writes.",
            "What is the checkout kill switch called now?",
            "checkout_halt_writes",
            "checkout_disable_all",
        ),
    ]
    rng.shuffle(cases)

    return [
        BenchmarkCase(
            name=name,
            observations=(
                Observation(old, 0, f"{name}:old"),
                Observation(new, 86_400, f"{name}:new", supersedes_source_ref=f"{name}:old"),
            ),
            queries=(
                BenchmarkQuery(
                    prompt=question,
                    expected=expected,
                    forbidden=forbidden,
                    now_unix=172_800,
                    changed_at_unix=86_400,
                ),
            ),
            metadata={"suite": "currencybench", "change": description},
        )
        for name, description, old, new, question, expected, forbidden in cases
    ]


def coding_agent_memory_task(seed: int = 7) -> list[BenchmarkCase]:
    """Return a compact long-horizon coding-agent memory scenario."""

    rng = random.Random(seed)
    observations = [
        Observation(
            "Rejected approach: do not add a global singleton store; tests need isolated stores.",
            0,
            "decision:singleton-rejected",
        ),
        Observation(
            "File move: core/src/retrieval.rs now owns recall ranking; old path core/src/rank.rs was removed.",
            120,
            "filemove:retrieval",
        ),
        Observation(
            "Decision: use source_ref prefixes for server namespace isolation.",
            240,
            "decision:namespace-prefix",
        ),
    ]
    rng.shuffle(observations)

    return [
        BenchmarkCase(
            name="coding-agent-memory",
            observations=tuple(observations),
            queries=(
                BenchmarkQuery(
                    prompt="Should we add a global singleton store for tests?",
                    expected="do not add a global singleton store",
                    forbidden="add a global singleton store",
                    now_unix=360,
                ),
                BenchmarkQuery(
                    prompt="Where should recall ranking changes go?",
                    expected="core/src/retrieval.rs",
                    forbidden="core/src/rank.rs",
                    now_unix=360,
                ),
            ),
            metadata={"suite": "coding-agent"},
        )
    ]


def load_jsonl_suite(path: Path, suite_name: str) -> list[BenchmarkCase]:
    """Load a neutral JSONL benchmark format for LoCoMo and LongMemEval adapters.

    Expected record shape:
    {"name": str, "observations": [{"content": str, "valid_from_unix": int}],
     "queries": [{"prompt": str, "expected": str, "forbidden": str | null,
                  "now_unix": int}]}
    """

    cases = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            cases.append(
                BenchmarkCase(
                    name=record.get("name", f"{suite_name}-{line_number}"),
                    observations=tuple(_observations(record.get("observations", []), line_number)),
                    queries=tuple(_queries(record.get("queries", []), line_number)),
                    metadata={"suite": suite_name, "source": str(path)},
                )
            )

    return cases


def _observations(values: Iterable[dict[str, object]], line_number: int) -> Iterable[Observation]:
    for index, value in enumerate(values):
        yield Observation(
            content=str(value["content"]),
            valid_from_unix=int(value.get("valid_from_unix", 0)),
            source_ref=str(value.get("source_ref", f"line-{line_number}:obs-{index}")),
            supersedes_source_ref=(
                None
                if value.get("supersedes_source_ref") is None
                else str(value.get("supersedes_source_ref"))
            ),
        )


def _queries(values: Iterable[dict[str, object]], line_number: int) -> Iterable[BenchmarkQuery]:
    for index, value in enumerate(values):
        forbidden = value.get("forbidden")
        yield BenchmarkQuery(
            prompt=str(value["prompt"]),
            expected=str(value["expected"]),
            forbidden=None if forbidden is None else str(forbidden),
            now_unix=int(value.get("now_unix", 0)),
            changed_at_unix=(
                None if value.get("changed_at_unix") is None else int(value["changed_at_unix"])
            ),
        )
