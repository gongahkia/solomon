"""ContinuityBench metric definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any


@dataclass(frozen=True)
class TaskScore:
    task_id: str
    category: str
    answer: str
    stale_answer: bool | None
    contradiction_correct: bool | None
    stable_correct: bool | None
    evidence_strength: int | None
    reported_credence: float | None
    tokens: int
    status: str = "ok"


def score_dataset(dataset: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    """Score system outputs against a ContinuityBench dataset."""

    outputs_by_task = {
        str(output["task_id"]): output for output in outputs.get("results", outputs.get("tasks", []))
    }
    task_scores = [
        score_task(task, outputs_by_task.get(str(task["task_id"]))) for task in dataset["tasks"]
    ]

    return {
        "metrics": aggregate_metrics(task_scores),
        "by_category": aggregate_by_category(task_scores),
        "per_task": [asdict(score) for score in task_scores],
    }


def score_task(task: dict[str, Any], output: dict[str, Any] | None) -> TaskScore:
    """Score one task output."""

    if output is None:
        return TaskScore(
            task_id=str(task["task_id"]),
            category=str(task["category"]),
            answer="missing",
            stale_answer=None,
            contradiction_correct=None,
            stable_correct=None,
            evidence_strength=None,
            reported_credence=None,
            tokens=0,
            status="missing",
        )

    contexts = [str(context) for context in output.get("contexts", [])]
    tokens = int(output.get("token_count", whitespace_token_count("\n".join(contexts))))
    category = str(task["category"])

    if category == "supersession":
        current = task["answers"]["current"]
        stale_answer = task["answers"]["stale"]
        stale = supersession_is_stale(contexts, current, stale_answer)
        answer = "stale" if stale else "current" if contains(contexts, current) else "missing"
        return base_score(task, output, tokens, answer=answer, stale=stale)

    if category == "contradiction":
        correct = contradiction_is_correct(
            contexts,
            task["answers"]["authoritative"],
            task["answers"]["rejected"],
        )
        return base_score(
            task,
            output,
            tokens,
            answer="authoritative" if correct else "rejected_or_missing",
            contradiction_correct=correct,
        )

    if category == "evidence-quality":
        credence = first_credence(output)
        return base_score(
            task,
            output,
            tokens,
            answer="current" if contains(contexts, task["answers"]["current"]) else "missing",
            evidence_strength=int(task["evidence"]["strength"]),
            reported_credence=credence,
        )

    if category == "stable-recall":
        correct = contains(contexts, task["answers"]["current"])
        return base_score(
            task,
            output,
            tokens,
            answer="current" if correct else "missing",
            stable_correct=correct,
        )

    raise ValueError(f"unknown ContinuityBench category: {category}")


def base_score(
    task: dict[str, Any],
    output: dict[str, Any],
    tokens: int,
    *,
    answer: str,
    stale: bool | None = None,
    contradiction_correct: bool | None = None,
    stable_correct: bool | None = None,
    evidence_strength: int | None = None,
    reported_credence: float | None = None,
) -> TaskScore:
    return TaskScore(
        task_id=str(task["task_id"]),
        category=str(task["category"]),
        answer=answer,
        stale_answer=stale,
        contradiction_correct=contradiction_correct,
        stable_correct=stable_correct,
        evidence_strength=evidence_strength,
        reported_credence=reported_credence,
        tokens=tokens,
        status=str(output.get("status", "ok")),
    )


def aggregate_metrics(task_scores: list[TaskScore]) -> dict[str, float | int | None]:
    """Compute Phase B headline metrics."""

    supersession = [score for score in task_scores if score.category == "supersession"]
    contradictions = [score for score in task_scores if score.category == "contradiction"]
    stable = [score for score in task_scores if score.category == "stable-recall"]
    evidence_pairs = [
        (float(score.reported_credence), float(score.evidence_strength))
        for score in task_scores
        if score.category == "evidence-quality"
        and score.reported_credence is not None
        and score.evidence_strength is not None
    ]

    return {
        "stale_answer_rate": ratio(
            sum(score.stale_answer is True for score in supersession),
            len(supersession),
        ),
        "contradiction_resolution_acc": ratio(
            sum(score.contradiction_correct is True for score in contradictions),
            len(contradictions),
        ),
        "credence_tracks_evidence_rho": spearman_rho(evidence_pairs),
        "credence_n": len(evidence_pairs),
        "mean_retrieval_tokens": mean([score.tokens for score in task_scores if score.status == "ok"]),
        "stable_recall_acc": ratio(
            sum(score.stable_correct is True for score in stable),
            len(stable),
        ),
    }


def aggregate_by_category(task_scores: list[TaskScore]) -> dict[str, dict[str, float | int | None]]:
    """Compute category-level summaries."""

    grouped: dict[str, list[TaskScore]] = {}
    for score in task_scores:
        grouped.setdefault(score.category, []).append(score)

    return {
        category: {
            "tasks": len(scores),
            "ok": sum(score.status == "ok" for score in scores),
            "mean_retrieval_tokens": mean([score.tokens for score in scores if score.status == "ok"]),
        }
        for category, scores in sorted(grouped.items())
    }


def supersession_is_stale(contexts: list[str], current: str, stale: str) -> bool:
    """Return the exact Phase B stale-answer rule for ranked contexts."""

    current_rank = first_rank(contexts, current)
    stale_rank = first_rank(contexts, stale)
    if stale_rank is None:
        return False
    if current_rank is None:
        return True
    return current_rank >= stale_rank


def contradiction_is_correct(contexts: list[str], authoritative: str, rejected: str) -> bool:
    """Return whether authoritative evidence is ranked before rejected evidence."""

    authoritative_rank = first_rank(contexts, authoritative)
    rejected_rank = first_rank(contexts, rejected)
    if authoritative_rank is None:
        return False
    return rejected_rank is None or authoritative_rank < rejected_rank


def contains(contexts: list[str], needle: str) -> bool:
    return first_rank(contexts, needle) is not None


def first_rank(contexts: list[str], needle: str) -> int | None:
    needle_folded = needle.casefold()
    for index, context in enumerate(contexts):
        if needle_folded in context.casefold():
            return index
    return None


def first_credence(output: dict[str, Any]) -> float | None:
    values = output.get("item_credences", [])
    if not values:
        return None
    return float(values[0])


def whitespace_token_count(text: str) -> int:
    return len(text.split())


def spearman_rho(pairs: list[tuple[float, float]]) -> float | None:
    """Compute Spearman rank correlation with average ranks for ties."""

    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs, strict=True)
    rank_x = ranks(list(xs))
    rank_y = ranks(list(ys))
    mean_x = fmean(rank_x)
    mean_y = fmean(rank_y)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(rank_x, rank_y, strict=True))
    denom_x = sum((x - mean_x) ** 2 for x in rank_x)
    denom_y = sum((y - mean_y) ** 2 for y in rank_y)
    denominator = (denom_x * denom_y) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def ranks(values: list[float]) -> list[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][0] == ordered[cursor][0]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for _, original_index in ordered[cursor:end]:
            result[original_index] = rank
        cursor = end
    return result


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def mean(values: list[int]) -> float | None:
    if not values:
        return None
    return fmean(values)
