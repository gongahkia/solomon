"""Benchmark task definitions and suite loaders."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


LOCOMO_SESSION_RE = re.compile(r"^session_(\d+)$")
LOCOMO_OBSERVATION_RE = re.compile(r"^session_(\d+)_observation$")


@dataclass(frozen=True)
class Observation:
    """One memory observation supplied to a system."""

    content: str
    valid_from_unix: int
    source_ref: str
    supersedes_source_ref: str | None = None
    reinforce_count: int = 0
    related_source_refs: tuple[str, ...] = ()


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
        if dataset is not None:
            return load_jsonl_suite(dataset, suite_name=name)
        return currencybench(seed)
    if name == "coding-agent":
        return coding_agent_memory_task(seed)
    if name == "ablation":
        return ablation_suite(seed)
    if name == "locomo":
        if dataset is None:
            raise ValueError(f"{name} requires --dataset JSON or JSONL")
        return load_dataset_suite(dataset, suite_name=name)
    if name == "longmemeval":
        if dataset is None:
            raise ValueError(f"{name} requires --dataset JSON or JSONL")
        return load_dataset_suite(dataset, suite_name=name)

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
        (
            "runbook-owner",
            "Runbook owner changed after on-call rotation",
            "The payments runbook owner is Omar.",
            "The payments runbook owner is Lin.",
            "Who owns the payments runbook now?",
            "Lin",
            "Omar",
        ),
        (
            "database-primary",
            "Database primary moved during failover",
            "The customer database primary is db-primary-a.",
            "The customer database primary is db-primary-c.",
            "Which customer database primary should be used?",
            "db-primary-c",
            "db-primary-a",
        ),
        (
            "release-branch",
            "Release branch advanced after cutover",
            "The release branch is release/2026-05.",
            "The release branch is release/2026-06.",
            "What is the current release branch?",
            "release/2026-06",
            "release/2026-05",
        ),
        (
            "incident-channel",
            "Incident channel moved to a new room",
            "Use #incident-war-room for active incidents.",
            "Use #incident-response for active incidents.",
            "Which channel should active incidents use?",
            "#incident-response",
            "#incident-war-room",
        ),
        (
            "cache-ttl",
            "Cache TTL changed after freshness review",
            "The profile cache TTL is 30 minutes.",
            "The profile cache TTL is 5 minutes.",
            "What is the profile cache TTL now?",
            "5 minutes",
            "30 minutes",
        ),
        (
            "model-alias",
            "Model alias changed after migration",
            "The summarizer model alias is summary-stable-v1.",
            "The summarizer model alias is summary-stable-v2.",
            "What summarizer model alias is current?",
            "summary-stable-v2",
            "summary-stable-v1",
        ),
        (
            "pricing-plan",
            "Pricing plan renamed before launch",
            "The team plan is called Growth.",
            "The team plan is called Pro.",
            "What is the team plan called now?",
            "Pro",
            "Growth",
        ),
        (
            "support-sla",
            "Support SLA changed for enterprise customers",
            "Enterprise support response time is 4 hours.",
            "Enterprise support response time is 1 hour.",
            "What is the current enterprise support response time?",
            "1 hour",
            "4 hours",
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


def ablation_suite(seed: int = 7) -> list[BenchmarkCase]:
    """Return deterministic cases that isolate core Shibahama feature toggles."""

    rng = random.Random(seed)
    cases = [
        BenchmarkCase(
            name="significance-ranking",
            observations=(
                Observation(
                    "The API client lives in src/client/http.py.",
                    0,
                    "ablation:significance:distractor",
                ),
                Observation(
                    "Decision: put API client changes in src/integrations/api_client.py after the module split.",
                    0,
                    "ablation:significance:decision",
                    reinforce_count=8,
                ),
            ),
            queries=(
                BenchmarkQuery(
                    prompt="Where should API client changes go?",
                    expected="src/integrations/api_client.py",
                    forbidden="src/client/http.py",
                    now_unix=120,
                ),
            ),
            metadata={"suite": "ablation", "toggle": "significance"},
        ),
        BenchmarkCase(
            name="reconstruction-supersession",
            observations=(
                Observation(
                    "The support escalation owner is Priya.",
                    0,
                    "ablation:reconstruction:old-owner",
                ),
                Observation(
                    "The support escalation owner is Mateo.",
                    60,
                    "ablation:reconstruction:new-owner",
                    supersedes_source_ref="ablation:reconstruction:old-owner",
                ),
            ),
            queries=(
                BenchmarkQuery(
                    prompt="Who owns support escalation?",
                    expected="Mateo",
                    forbidden="Priya",
                    now_unix=120,
                    changed_at_unix=60,
                ),
            ),
            metadata={"suite": "ablation", "toggle": "reconstruction"},
        ),
        BenchmarkCase(
            name="graph-expansion",
            observations=(
                Observation(
                    "Runbook RB-42 links the payments incident to its current owner record.",
                    0,
                    "ablation:graph:anchor",
                    related_source_refs=("ablation:graph:owner",),
                ),
                Observation(
                    "The current payments escalation owner is Nina.",
                    0,
                    "ablation:graph:owner",
                ),
            ),
            queries=(
                BenchmarkQuery(
                    prompt="Which runbook links the payments incident?",
                    expected="Nina",
                    now_unix=120,
                ),
            ),
            metadata={"suite": "ablation", "toggle": "graph"},
        ),
    ]
    rng.shuffle(cases)

    return cases


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
                    metadata={
                        "suite": suite_name,
                        "source": str(path),
                        "source_format": "shibahama-jsonl",
                    },
                )
            )

    return cases


def load_dataset_suite(path: Path, suite_name: str) -> list[BenchmarkCase]:
    """Load a benchmark suite from either Shibahama JSONL or an official JSON export."""

    if path.suffix == ".jsonl":
        return load_jsonl_suite(path, suite_name=suite_name)

    data = json.loads(path.read_text(encoding="utf-8"))
    if suite_name == "locomo":
        return load_locomo_export(data, path)
    if suite_name == "longmemeval":
        return load_longmemeval_export(data, path)

    raise ValueError(f"unsupported dataset suite: {suite_name}")


def load_locomo_export(data: object, path: Path) -> list[BenchmarkCase]:
    """Load the official LoCoMo ``locomo10.json`` export."""

    if not isinstance(data, list):
        raise ValueError("LoCoMo export must be a JSON array of conversation samples")

    cases = []
    for sample_index, sample in enumerate(data, start=1):
        if not isinstance(sample, dict):
            raise ValueError(f"LoCoMo sample {sample_index} must be an object")

        sample_id = str(sample.get("sample_id", f"locomo-{sample_index}"))
        observations = tuple(_locomo_observations(sample, sample_id))
        if not observations:
            raise ValueError(f"LoCoMo sample {sample_id} has no loadable observations")

        now_unix = max(observation.valid_from_unix for observation in observations)
        queries = tuple(_locomo_queries(sample, now_unix))
        if not queries:
            continue

        cases.append(
            BenchmarkCase(
                name=sample_id,
                observations=observations,
                queries=queries,
                metadata={
                    "suite": "locomo",
                    "source": str(path),
                    "source_format": "official-locomo-json",
                    "sample_id": sample_id,
                },
            )
        )

    return cases


def load_longmemeval_export(data: object, path: Path) -> list[BenchmarkCase]:
    """Load an official LongMemEval JSON export from Hugging Face."""

    if isinstance(data, dict) and isinstance(data.get("data"), list):
        records = data["data"]
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError("LongMemEval export must be a JSON array of evaluation records")

    cases = []
    for record_index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"LongMemEval record {record_index} must be an object")

        question_id = str(record.get("question_id", f"longmemeval-{record_index}"))
        observations = tuple(_longmemeval_observations(record, question_id))
        if not observations:
            raise ValueError(f"LongMemEval record {question_id} has no haystack sessions")

        now_unix = _parse_timestamp(
            record.get("question_date"),
            fallback=max(observation.valid_from_unix for observation in observations),
        )
        answer = _normalise_answer(record.get("answer", ""))
        if not answer:
            continue

        cases.append(
            BenchmarkCase(
                name=question_id,
                observations=observations,
                queries=(
                    BenchmarkQuery(
                        prompt=str(record.get("question", "")),
                        expected=answer,
                        now_unix=now_unix,
                    ),
                ),
                metadata={
                    "suite": "longmemeval",
                    "source": str(path),
                    "source_format": "official-longmemeval-json",
                    "question_id": question_id,
                    "question_type": str(record.get("question_type", "")),
                },
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
            reinforce_count=int(value.get("reinforce_count", 0)),
            related_source_refs=tuple(
                str(source_ref) for source_ref in value.get("related_source_refs", [])
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


def _locomo_observations(sample: dict[str, object], sample_id: str) -> Iterator[Observation]:
    conversation = _dict_value(sample.get("conversation"))
    generated = _dict_value(sample.get("observation"))

    for key, value in sorted(generated.items(), key=lambda item: _locomo_observation_sort(item[0])):
        match = LOCOMO_OBSERVATION_RE.match(str(key))
        if match is None:
            continue

        session_number = int(match.group(1))
        valid_from_unix = _locomo_session_timestamp(conversation, session_number)
        speakers = _dict_value(value)
        for speaker, entries in speakers.items():
            for index, entry in enumerate(_list_value(entries)):
                statement, evidence_ref = _locomo_observation_entry(entry, session_number, index)
                if not statement:
                    continue

                source_ref = (
                    f"{sample_id}:{evidence_ref}"
                    if evidence_ref
                    else f"{sample_id}:session_{session_number}:obs_{index}"
                )
                yield Observation(
                    content=f"{speaker}: {statement}",
                    valid_from_unix=valid_from_unix,
                    source_ref=source_ref,
                )

    if generated:
        return

    for session_number, turns in _locomo_conversation_sessions(conversation):
        valid_from_unix = _locomo_session_timestamp(conversation, session_number)
        for index, turn in enumerate(_list_value(turns)):
            turn_object = _dict_value(turn)
            text = str(turn_object.get("text", "")).strip()
            if not text:
                continue

            speaker = str(turn_object.get("speaker", "speaker"))
            dia_id = str(turn_object.get("dia_id", f"D{session_number}:{index + 1}"))
            yield Observation(
                content=f"{speaker}: {text}",
                valid_from_unix=valid_from_unix,
                source_ref=f"{sample_id}:{dia_id}",
            )


def _locomo_queries(sample: dict[str, object], now_unix: int) -> Iterator[BenchmarkQuery]:
    for qa in _list_value(sample.get("qa")):
        qa_object = _dict_value(qa)
        answer = _normalise_answer(qa_object.get("answer", ""))
        question = str(qa_object.get("question", "")).strip()
        if not question or not answer:
            continue

        yield BenchmarkQuery(
            prompt=question,
            expected=answer,
            now_unix=now_unix,
        )


def _longmemeval_observations(
    record: dict[str, object], question_id: str
) -> Iterator[Observation]:
    sessions = _list_value(record.get("haystack_sessions"))
    dates = _list_value(record.get("haystack_dates"))
    session_ids = _list_value(record.get("haystack_session_ids"))

    for index, session in enumerate(sessions):
        session_id = str(_at_or_default(session_ids, index, f"session-{index + 1}"))
        valid_from_unix = _parse_timestamp(_at_or_default(dates, index, index), fallback=index)
        content = _longmemeval_session_text(session)
        if not content:
            continue

        yield Observation(
            content=content,
            valid_from_unix=valid_from_unix,
            source_ref=f"{question_id}:{session_id}",
        )


def _longmemeval_session_text(session: object) -> str:
    turns = []
    for turn in _list_value(session):
        turn_object = _dict_value(turn)
        role = str(turn_object.get("role", "message"))
        content = str(turn_object.get("content", "")).strip()
        if content:
            turns.append(f"{role}: {content}")

    return "\n".join(turns)


def _locomo_conversation_sessions(
    conversation: dict[str, object]
) -> Iterator[tuple[int, object]]:
    for key, value in sorted(conversation.items(), key=lambda item: _locomo_session_sort(item[0])):
        match = LOCOMO_SESSION_RE.match(str(key))
        if match is not None:
            yield int(match.group(1)), value


def _locomo_session_timestamp(conversation: dict[str, object], session_number: int) -> int:
    key = f"session_{session_number}_date_time"
    return _parse_timestamp(conversation.get(key), fallback=session_number)


def _locomo_observation_entry(
    entry: object, session_number: int, index: int
) -> tuple[str, str | None]:
    if isinstance(entry, list) and entry:
        evidence_ref = None if len(entry) < 2 else str(entry[1])
        return str(entry[0]).strip(), evidence_ref
    if isinstance(entry, dict):
        evidence_ref = entry.get("dia_id") or entry.get("evidence")
        return str(entry.get("text", entry.get("content", ""))).strip(), (
            None if evidence_ref is None else str(evidence_ref)
        )

    return str(entry).strip(), f"D{session_number}:{index + 1}"


def _parse_timestamp(value: object, fallback: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if value is None:
        return fallback

    text = str(value).strip()
    if not text:
        return fallback
    if text.isdigit():
        return int(text)

    normalised = re.sub(
        r"\b(am|pm)\b",
        lambda match: match.group(1).upper(),
        text,
        flags=re.IGNORECASE,
    )
    for pattern in (
        "%Y/%m/%d (%a) %H:%M",
        "%I:%M %p on %d %B, %Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(normalised, pattern)
        except ValueError:
            continue

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())

    return fallback


def _normalise_answer(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [_normalise_answer(item) for item in value]
        return "; ".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value).strip()


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _at_or_default(values: list[object], index: int, default: object) -> object:
    return values[index] if index < len(values) else default


def _locomo_session_sort(key: object) -> tuple[int, str]:
    match = LOCOMO_SESSION_RE.match(str(key))
    return (int(match.group(1)), str(key)) if match else (10**9, str(key))


def _locomo_observation_sort(key: object) -> tuple[int, str]:
    match = LOCOMO_OBSERVATION_RE.match(str(key))
    return (int(match.group(1)), str(key)) if match else (10**9, str(key))
