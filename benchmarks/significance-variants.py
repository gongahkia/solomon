#!/usr/bin/env python3
"""Compare significance-function parameter variants on deterministic histories."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class AccessEvent:
    """One historical usage signal."""

    day: int
    outcome: str


@dataclass(frozen=True)
class MemoryScenario:
    """One synthetic memory history used for offline comparison."""

    name: str
    base_score: float
    ingested_day: int
    graph_centrality: float
    access_events: tuple[AccessEvent, ...]


@dataclass(frozen=True)
class SignificanceVariant:
    """Significance parameters matching the Rust `SignificanceConfig` shape."""

    name: str
    half_life_days: float = 30.0
    reinforcement_weight: float = 1.0
    surfaced_weight: float = 0.1
    led_somewhere_weight: float = 1.0
    cited_weight: float = 1.25
    ignored_weight: float = -0.05
    contradicted_weight: float = -2.0
    graph_centrality_weight: float = 0.0
    warm_threshold: float = 1.0
    hot_threshold: float = 2.0


@dataclass(frozen=True)
class VariantResult:
    """One scenario scored under one significance variant."""

    scenario: str
    variant: str
    final_score: float
    tier: str
    decay_multiplier: float
    decayed_base: float
    reinforcement: float
    outcome_bonus: float
    contradiction_penalty: float
    graph_centrality: float


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now-days", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/significance-variants.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("benchmarks/results/significance-variants.md"),
    )
    args = parser.parse_args()

    if args.now_days <= 0:
        raise SystemExit("--now-days must be positive")

    results = [
        score_scenario(scenario, variant, args.now_days)
        for scenario in scenarios()
        for variant in variants()
    ]
    write_json(args.output, results, args.now_days)
    write_markdown(args.markdown, results, args.now_days)
    print(f"wrote {args.output}")
    print(f"wrote {args.markdown}")
    return 0


def scenarios() -> tuple[MemoryScenario, ...]:
    """Return deterministic histories that stress different significance terms."""

    return (
        MemoryScenario(
            name="stale-authoritative-decision",
            base_score=1.2,
            ingested_day=0,
            graph_centrality=0.4,
            access_events=(
                AccessEvent(day=1, outcome="cited"),
                AccessEvent(day=14, outcome="led_somewhere"),
                AccessEvent(day=45, outcome="surfaced"),
            ),
        ),
        MemoryScenario(
            name="frequent-but-contradicted-web-note",
            base_score=0.6,
            ingested_day=7,
            graph_centrality=0.1,
            access_events=(
                AccessEvent(day=8, outcome="surfaced"),
                AccessEvent(day=15, outcome="ignored"),
                AccessEvent(day=30, outcome="surfaced"),
                AccessEvent(day=60, outcome="contradicted"),
                AccessEvent(day=61, outcome="contradicted"),
            ),
        ),
        MemoryScenario(
            name="recent-tool-observation",
            base_score=0.8,
            ingested_day=100,
            graph_centrality=0.2,
            access_events=(
                AccessEvent(day=101, outcome="led_somewhere"),
                AccessEvent(day=119, outcome="cited"),
            ),
        ),
        MemoryScenario(
            name="graph-central-hub-fact",
            base_score=0.7,
            ingested_day=20,
            graph_centrality=2.0,
            access_events=(AccessEvent(day=25, outcome="surfaced"),),
        ),
    )


def variants() -> tuple[SignificanceVariant, ...]:
    """Return parameter variants to compare offline."""

    return (
        SignificanceVariant(name="default"),
        SignificanceVariant(name="slow-decay", half_life_days=90.0),
        SignificanceVariant(
            name="outcome-heavy",
            led_somewhere_weight=1.5,
            cited_weight=2.0,
        ),
        SignificanceVariant(name="graph-aware", graph_centrality_weight=0.5),
        SignificanceVariant(name="strict-contradiction", contradicted_weight=-4.0),
    )


def score_scenario(
    scenario: MemoryScenario,
    variant: SignificanceVariant,
    now_days: int,
) -> VariantResult:
    """Compute one deterministic significance breakdown."""

    last_used_day = max(
        (event.day for event in scenario.access_events),
        default=scenario.ingested_day,
    )
    elapsed_seconds = max(0, now_days - last_used_day) * SECONDS_PER_DAY
    half_life_seconds = variant.half_life_days * SECONDS_PER_DAY
    decay_multiplier = 0.5 ** (elapsed_seconds / half_life_seconds)
    decayed_base = scenario.base_score * decay_multiplier
    reinforcement = variant.reinforcement_weight * math.log1p(len(scenario.access_events))
    outcome_bonus = sum(outcome_weight(event.outcome, variant) for event in scenario.access_events)
    contradiction_penalty = (
        sum(1 for event in scenario.access_events if event.outcome == "contradicted")
        * abs(variant.contradicted_weight)
    )
    graph_centrality = variant.graph_centrality_weight * scenario.graph_centrality
    final_score = (
        decayed_base
        + reinforcement
        + outcome_bonus
        + graph_centrality
        - contradiction_penalty
    )

    return VariantResult(
        scenario=scenario.name,
        variant=variant.name,
        final_score=round(final_score, 4),
        tier=tier_for_score(final_score, variant),
        decay_multiplier=round(decay_multiplier, 4),
        decayed_base=round(decayed_base, 4),
        reinforcement=round(reinforcement, 4),
        outcome_bonus=round(outcome_bonus, 4),
        contradiction_penalty=round(contradiction_penalty, 4),
        graph_centrality=round(graph_centrality, 4),
    )


def outcome_weight(outcome: str, variant: SignificanceVariant) -> float:
    """Return a variant's configured contribution for one outcome."""

    weights = {
        "surfaced": variant.surfaced_weight,
        "led_somewhere": variant.led_somewhere_weight,
        "cited": variant.cited_weight,
        "ignored": variant.ignored_weight,
        "contradicted": variant.contradicted_weight,
    }
    return weights[outcome]


def tier_for_score(score: float, variant: SignificanceVariant) -> str:
    """Classify score using promotion thresholds."""

    if score >= variant.hot_threshold:
        return "hot"
    if score >= variant.warm_threshold:
        return "warm"
    return "cold"


def write_json(path: Path, results: list[VariantResult], now_days: int) -> None:
    """Write detailed variant results."""

    payload = {
        "config": {
            "benchmark": "significance-variants",
            "now_days": now_days,
            "variants": [asdict(variant) for variant in variants()],
            "scenarios": [asdict(scenario) for scenario in scenarios()],
        },
        "results": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, results: list[VariantResult], now_days: int) -> None:
    """Write a compact Markdown table sorted by scenario and score."""

    lines = [
        "# Significance Variant Results",
        "",
        f"`now_days`: {now_days}",
        "",
        "| Scenario | Rank | Variant | Score | Tier | Decay | Reinforcement | Outcome | Contradiction | Graph |",
        "| --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for scenario in sorted({result.scenario for result in results}):
        scenario_results = sorted(
            [result for result in results if result.scenario == scenario],
            key=lambda result: result.final_score,
            reverse=True,
        )
        for rank, result in enumerate(scenario_results, start=1):
            lines.append(
                "| {scenario} | {rank} | {variant} | {score:.4f} | {tier} | "
                "{decay:.4f} | {reinforcement:.4f} | {outcome:.4f} | "
                "{contradiction:.4f} | {graph:.4f} |".format(
                    scenario=result.scenario,
                    rank=rank,
                    variant=result.variant,
                    score=result.final_score,
                    tier=result.tier,
                    decay=result.decay_multiplier,
                    reinforcement=result.reinforcement,
                    outcome=result.outcome_bonus,
                    contradiction=result.contradiction_penalty,
                    graph=result.graph_centrality,
                )
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
