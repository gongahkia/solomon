#!/usr/bin/env python3
"""Run ContinuityBench local and external baselines."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "bindings" / "python" / "python"))

from continuity.metrics import score_dataset, whitespace_token_count
from continuity.score import dataset_hash, format_value
from shibahama_bench.embeddings import embed_text


DEFAULT_DATASET = ROOT / "benchmarks" / "continuity" / "dataset" / "continuitybench-v0.json"
DEFAULT_OUTPUT_DIR = ROOT / "benchmarks" / "results" / "continuity"
DEFAULT_SYSTEMS = "shibahama,warehouse,full-context,mem0-oss-exact"
TOP_K = 5
SHIBAHAMA_DIMENSIONS = 16
MEM0_EMBEDDER_MODEL = "BAAI/bge-small-en-v1.5"
MEM0_EMBEDDING_DIMENSIONS = 384


class BaselineAdapter(Protocol):
    name: str
    model: str
    tokenizer: str
    config: dict[str, Any]

    def reset(self, task: dict[str, Any]) -> None: ...

    def ingest(self, event: dict[str, Any]) -> None: ...

    def query(self, task: dict[str, Any], top_k: int) -> dict[str, Any]: ...


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--systems", default=DEFAULT_SYSTEMS)
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    command = shlex.join(sys.argv)
    payloads = []

    with tempfile.TemporaryDirectory(prefix="continuitybench-") as tmpdir:
        for system in [name.strip() for name in args.systems.split(",") if name.strip()]:
            adapter = build_adapter(system, Path(tmpdir))
            system_output = run_adapter(dataset, adapter, args.top_k, args.seed)
            payload = result_payload(dataset, system_output, adapter, command)
            write_result(args.output_dir, payload)
            payloads.append(payload)

    write_summary(args.output_dir / "SUMMARY.md", payloads)
    print(f"wrote {args.output_dir}")
    return 0


def build_adapter(system: str, tmpdir: Path) -> BaselineAdapter:
    if system == "shibahama":
        return ShibahamaContinuityAdapter(tmpdir / "shibahama")
    if system == "warehouse":
        return WarehouseContinuityAdapter()
    if system == "full-context":
        return FullContextAdapter()
    if system == "mem0-oss-exact":
        return Mem0OssExactAdapter(tmpdir / "mem0")
    raise ValueError(f"unknown continuity baseline: {system}")


def run_adapter(
    dataset: dict[str, Any],
    adapter: BaselineAdapter,
    top_k: int,
    seed: int,
) -> dict[str, Any]:
    results = []
    for task in dataset["tasks"]:
        adapter.reset(task)
        for event in sorted(task["events"], key=lambda value: value["t"]):
            adapter.ingest(event)
        result = adapter.query(task, top_k)
        result["task_id"] = task["task_id"]
        results.append(result)

    return {
        "system": adapter.name,
        "model": adapter.model,
        "seed": seed,
        "tokenizer": adapter.tokenizer,
        "baseline_config": adapter.config | {"top_k": top_k},
        "results": results,
    }


def result_payload(
    dataset: dict[str, Any],
    system_output: dict[str, Any],
    adapter: BaselineAdapter,
    command: str,
) -> dict[str, Any]:
    scored = score_dataset(dataset, system_output)
    return {
        "manifest": {
            "system": adapter.name,
            "dataset_hash": f"sha256:{dataset_hash(dataset)}",
            "model": adapter.model,
            "seed": system_output["seed"],
            "tokenizer": adapter.tokenizer,
            "judge_prompt_hash": None,
            "commit": git_commit(),
            "command": command,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "baseline_config": system_output["baseline_config"],
        },
        **scored,
    }


def write_result(output_dir: Path, payload: dict[str, Any]) -> None:
    system = payload["manifest"]["system"]
    (output_dir / f"{system}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{system}.md").write_text(result_markdown(payload), encoding="utf-8")


def result_markdown(payload: dict[str, Any]) -> str:
    manifest = payload["manifest"]
    metrics = payload["metrics"]
    return "\n".join(
        [
            f"# ContinuityBench Result: {manifest['system']}",
            "",
            f"- dataset: `{manifest['dataset_hash']}`",
            f"- model/config: `{manifest['model']}`",
            f"- tokenizer: `{manifest['tokenizer']}`",
            f"- commit: `{manifest['commit']}`",
            "",
            "| stale-answer rate | contradiction acc | credence rho | credence n | mean tokens | stable recall acc |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            "| {stale} | {contradiction} | {rho} | {n} | {tokens} | {stable} |".format(
                stale=format_value(metrics["stale_answer_rate"]),
                contradiction=format_value(metrics["contradiction_resolution_acc"]),
                rho=format_value(metrics["credence_tracks_evidence_rho"]),
                n=format_value(metrics["credence_n"]),
                tokens=format_value(metrics["mean_retrieval_tokens"]),
                stable=format_value(metrics["stable_recall_acc"]),
            ),
            "",
        ]
    )


def write_summary(path: Path, payloads: list[dict[str, Any]]) -> None:
    shibahama = next(
        (payload for payload in payloads if payload["manifest"]["system"] == "shibahama"),
        None,
    )
    lines = [
        "# ContinuityBench Summary",
        "",
        "| System | Stale Rate | Contradiction Acc | Credence Rho | Credence n | Mean Tokens | Stable Acc | Where Shibahama Loses/Ties |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for payload in payloads:
        metrics = payload["metrics"]
        lines.append(
            "| {system} | {stale} | {contradiction} | {rho} | {n} | {tokens} | {stable} | {losses} |".format(
                system=payload["manifest"]["system"],
                stale=format_value(metrics["stale_answer_rate"]),
                contradiction=format_value(metrics["contradiction_resolution_acc"]),
                rho=format_value(metrics["credence_tracks_evidence_rho"]),
                n=format_value(metrics["credence_n"]),
                tokens=format_value(metrics["mean_retrieval_tokens"]),
                stable=format_value(metrics["stable_recall_acc"]),
                losses=loss_column(shibahama, payload),
            )
        )
    lines.extend(
        [
            "",
            "Mem0 OSS is run as an exact-event retrieval baseline: `mem0ai` stores the dataset event text directly with `infer=False`, FastEmbed embeddings, and local Qdrant. This avoids hosted LLM/API-key extraction and isolates retrieval behavior.",
            "",
            "Full-context returns every event for the task, ranked by valid-time and corroboration for deterministic scoring; its token cost is the relevant baseline cost.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def loss_column(shibahama: dict[str, Any] | None, payload: dict[str, Any]) -> str:
    if shibahama is None or payload is shibahama:
        return "baseline row"
    shib = shibahama["metrics"]
    other = payload["metrics"]
    losses = []
    if metric_lt(other["stale_answer_rate"], shib["stale_answer_rate"]):
        losses.append("stale rate")
    if metric_gt(other["contradiction_resolution_acc"], shib["contradiction_resolution_acc"]):
        losses.append("contradiction")
    if metric_gt(other["credence_tracks_evidence_rho"], shib["credence_tracks_evidence_rho"]):
        losses.append("credence rho")
    if metric_lt(other["mean_retrieval_tokens"], shib["mean_retrieval_tokens"]):
        losses.append("tokens")
    if metric_gt(other["stable_recall_acc"], shib["stable_recall_acc"]):
        losses.append("stable recall")
    if not losses:
        return "none on headline metrics"
    return ", ".join(losses)


def metric_lt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left < right


def metric_gt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left > right


class ShibahamaContinuityAdapter:
    name = "shibahama"
    model = "shibahama-python-binding+deterministic-blake2b-embeddings"
    tokenizer = "whitespace"

    def __init__(self, tmpdir: Path) -> None:
        import shibahama

        self._module = shibahama
        self._tmpdir = tmpdir
        self._tmpdir.mkdir(parents=True, exist_ok=True)
        self._engine = None
        self._ids_by_fact: dict[str, str] = {}
        self.config = {
            "dimensions": SHIBAHAMA_DIMENSIONS,
            "supersession": "invalidate superseded fact before writing current event",
            "credence_output": "mapped from Shibahama credence tier",
        }

    def reset(self, task: dict[str, Any]) -> None:
        path = self._tmpdir / f"{task['task_id']}.redb"
        if path.exists():
            path.unlink()
        self._engine = self._module.Shibahama(str(path), SHIBAHAMA_DIMENSIONS, 1024)
        self._ids_by_fact = {}

    def ingest(self, event: dict[str, Any]) -> None:
        assert self._engine is not None
        if event.get("supersedes"):
            superseded_id = self._ids_by_fact.get(str(event["supersedes"]))
            if superseded_id:
                self._engine.invalidate(superseded_id, unix_seconds(event["t"]))
        item = self._engine.write(
            event["content"],
            vector=embed_text(event["content"], SHIBAHAMA_DIMENSIONS),
            source_kind=shibahama_source_kind(event["provenance"]["kind"]),
            source_ref=event["provenance"]["ref"],
            ingested_by="continuitybench",
            valid_from_unix=unix_seconds(event["t"]),
            ingested_at_unix=unix_seconds(event["t"]),
        )
        self._ids_by_fact[str(event["establishes"])] = item.id

    def query(self, task: dict[str, Any], top_k: int) -> dict[str, Any]:
        assert self._engine is not None
        candidates = self._engine.recall(
            embed_text(task["query"]["text"], SHIBAHAMA_DIMENSIONS),
            top_k,
            now_unix=unix_seconds(task["query"]["t"]),
            raw_query_context=task["query"]["text"],
            include_cold=True,
        )
        contexts = [candidate.item.content for candidate in candidates]
        return {
            "contexts": contexts,
            "item_credences": [credence_value(candidate.item.credence) for candidate in candidates],
            "token_count": whitespace_token_count("\n".join(contexts)),
        }


class WarehouseContinuityAdapter:
    name = "warehouse"
    model = "append-only-keyword-overlap"
    tokenizer = "whitespace"
    config = {"ranking": "keyword overlap, append-order tie break, no invalidation"}

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def reset(self, task: dict[str, Any]) -> None:
        self._rows = []

    def ingest(self, event: dict[str, Any]) -> None:
        self._rows.append(event)

    def query(self, task: dict[str, Any], top_k: int) -> dict[str, Any]:
        prompt_terms = terms(task["query"]["text"])
        scored = []
        for index, event in enumerate(self._rows):
            overlap = len(prompt_terms & terms(event["content"]))
            scored.append((overlap, -index, event["content"]))
        scored.sort(reverse=True)
        contexts = [content for overlap, _, content in scored[:top_k] if overlap > 0]
        return {
            "contexts": contexts,
            "item_credences": [],
            "token_count": whitespace_token_count("\n".join(contexts)),
        }


class FullContextAdapter:
    name = "full-context"
    model = "all-task-events-ranked-by-valid-time-and-corroboration"
    tokenizer = "whitespace"
    config = {"ranking": "all task events, newest first, corroboration tie-break"}

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def reset(self, task: dict[str, Any]) -> None:
        self._rows = []

    def ingest(self, event: dict[str, Any]) -> None:
        self._rows.append(event)

    def query(self, task: dict[str, Any], top_k: int) -> dict[str, Any]:
        contexts = [
            event["content"]
            for event in sorted(
                self._rows,
                key=lambda event: (event["t"], event["provenance"]["corroboration"]),
                reverse=True,
            )
        ]
        return {
            "contexts": contexts,
            "item_credences": [],
            "token_count": whitespace_token_count("\n".join(contexts)),
        }


class Mem0OssExactAdapter:
    name = "mem0-oss-exact"
    model = f"mem0ai+fastembed:{MEM0_EMBEDDER_MODEL}"
    tokenizer = "whitespace"

    def __init__(self, tmpdir: Path) -> None:
        from mem0 import Memory
        import mem0

        self._memory_cls = Memory
        self._mem0_version = getattr(mem0, "__version__", "unknown")
        self._tmpdir = tmpdir
        self._tmpdir.mkdir(parents=True, exist_ok=True)
        self._memory = None
        self._task_id = ""
        self.config = {
            "mem0_version": self._mem0_version,
            "add_infer": False,
            "embedder": "fastembed",
            "embedder_model": MEM0_EMBEDDER_MODEL,
            "vector_store": "qdrant-local",
            "embedding_dimensions": MEM0_EMBEDDING_DIMENSIONS,
            "llm": "openai client initialized with dummy key; not called because infer=False",
        }

    def reset(self, task: dict[str, Any]) -> None:
        self._task_id = str(task["task_id"])
        path = self._tmpdir / self._task_id
        path.mkdir(parents=True, exist_ok=True)
        config = {
            "version": "v1.1",
            "embedder": {
                "provider": "fastembed",
                "config": {"model": MEM0_EMBEDDER_MODEL},
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": f"continuity_{self._task_id.replace('-', '_')}",
                    "embedding_model_dims": MEM0_EMBEDDING_DIMENSIONS,
                    "path": str(path / "qdrant"),
                },
            },
            "llm": {"provider": "openai", "config": {"api_key": "dummy", "model": "gpt-5-mini"}},
            "history_db_path": str(path / "history.db"),
        }
        self._memory = self._memory_cls.from_config(config)

    def ingest(self, event: dict[str, Any]) -> None:
        assert self._memory is not None
        self._memory.add(
            event["content"],
            user_id=self._task_id,
            metadata={"event_id": event["event_id"]},
            infer=False,
        )

    def query(self, task: dict[str, Any], top_k: int) -> dict[str, Any]:
        assert self._memory is not None
        result = self._memory.search(
            task["query"]["text"],
            filters={"user_id": self._task_id},
            top_k=top_k,
        )
        rows = result.get("results", result if isinstance(result, list) else [])
        contexts = [str(row.get("memory", "")) for row in rows]
        return {
            "contexts": contexts,
            "item_credences": [],
            "token_count": whitespace_token_count("\n".join(contexts)),
        }


def terms(value: str) -> set[str]:
    return set(value.casefold().replace("/", " ").replace("_", " ").replace("-", " ").split())


def shibahama_source_kind(kind: str) -> str:
    return {
        "file": "file",
        "human": "user",
        "runtime-log": "tool",
        "tool": "tool",
        "todo": "web",
        "chat": "web",
    }.get(kind, "user")


def credence_value(value: str) -> float:
    return {
        "unverified": 1.0,
        "model_inferred": 2.0,
        "verified_source": 3.0,
        "firm_authoritative": 4.0,
    }.get(value, 0.0)


def unix_seconds(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp())


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


if __name__ == "__main__":
    raise SystemExit(main())
