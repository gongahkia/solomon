"""Benchmark metrics and reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class BenchmarkResult:
    """One query result from one memory system."""

    suite: str
    case: str
    system: str
    prompt: str
    expected: str
    forbidden: str | None
    answer: str
    latency_ms: float
    retrieval_token_cost: int
    correct: bool
    stale_answer: bool
    time_to_correction_seconds: int | None
    status: str = "ok"


def score_answer(answer: str, expected: str, forbidden: str | None) -> tuple[bool, bool]:
    """Return correctness and stale-answer flags."""

    answer_folded = answer.casefold()
    expected_ok = expected.casefold() in answer_folded
    stale = bool(forbidden and forbidden.casefold() in answer_folded)

    return expected_ok and not stale, stale or not expected_ok


def token_cost(text: str) -> int:
    """Approximate retrieval token cost with whitespace tokens."""

    return len(text.split())


def summarize_results(results: list[BenchmarkResult]) -> list[dict[str, object]]:
    """Summarize query-level results by system and suite."""

    groups: dict[tuple[str, str], list[BenchmarkResult]] = {}

    for result in results:
        groups.setdefault((result.suite, result.system), []).append(result)

    rows = []
    for (suite, system), values in sorted(groups.items()):
        ok_values = [value for value in values if value.status == "ok"]
        latencies = sorted(value.latency_ms for value in ok_values)
        p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95)) if latencies else 0
        rows.append(
            {
                "suite": suite,
                "system": system,
                "queries": len(values),
                "accuracy": _ratio(sum(value.correct for value in ok_values), len(ok_values)),
                "stale_answer_rate": _ratio(
                    sum(value.stale_answer for value in ok_values), len(ok_values)
                ),
                "mean_token_cost": _mean([value.retrieval_token_cost for value in ok_values]),
                "mean_time_to_correction_seconds": _mean(
                    [
                        value.time_to_correction_seconds
                        for value in ok_values
                        if value.time_to_correction_seconds is not None
                    ]
                ),
                "latency_p50_ms": median(latencies) if latencies else None,
                "latency_p95_ms": latencies[p95_index] if latencies else None,
                "status": "ok" if len(ok_values) == len(values) else "partial",
            }
        )

    return rows


def write_json(
    path: Path, results: list[BenchmarkResult], config: dict[str, object] | None = None
) -> None:
    """Write query-level results and summaries."""

    payload = {
        "config": config or {},
        "results": [asdict(result) for result in results],
        "summary": summarize_results(results),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, results: list[BenchmarkResult]) -> None:
    """Write a Markdown summary table."""

    rows = summarize_results(results)
    lines = [
        "# Benchmark Results",
        "",
        "| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Correction Lag s | p50 ms | p95 ms | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for row in rows:
        lines.append(
            "| {suite} | {system} | {queries} | {accuracy} | {stale_answer_rate} | "
            "{mean_token_cost} | {mean_time_to_correction_seconds} | {latency_p50_ms} | "
            "{latency_p95_ms} | {status} |".format(
                suite=row["suite"],
                system=row["system"],
                queries=row["queries"],
                accuracy=_format_number(row["accuracy"]),
                stale_answer_rate=_format_number(row["stale_answer_rate"]),
                mean_token_cost=_format_number(row["mean_token_cost"]),
                mean_time_to_correction_seconds=_format_number(
                    row["mean_time_to_correction_seconds"]
                ),
                latency_p50_ms=_format_number(row["latency_p50_ms"]),
                latency_p95_ms=_format_number(row["latency_p95_ms"]),
                status=row["status"],
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _mean(values: list[int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _format_number(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
