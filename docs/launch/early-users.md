# Early-User Outreach Notes

## Who To Ask First

Prioritize users who already feel the pain of long-lived agent memory rather
than broad AI-tool audiences.

- Maintainers of coding-agent tools that keep project context across sessions.
- Teams building internal support or operations agents with changing facts.
- Developers evaluating agent memory systems who can run local benchmarks.
- Security-minded users who care about prompt injection from stored memory.
- People maintaining knowledge bases where stale answers are worse than missing
  answers.

## Outreach Message

Subject: Looking for early feedback on Shibahama, an embeddable agent-memory engine

I am testing Shibahama, a small Rust/Python/Node memory engine for long-lived
agents. It focuses on currency-aware recall: remembering not just facts, but
whether a fact was superseded, low-trust, rejected, or needs re-validation.

The repo includes a coding-agent demo, local benchmarks, and a visual debugger
called Tideline. The narrow thing I would like feedback on is whether the memory
model matches failures you have seen: repeated rejected suggestions, stale file
paths, untrusted model-written notes, or old facts that should be revisited
instead of silently reused.

If this overlaps with your work, the most useful feedback would be:

- what task you tried;
- whether setup was clear;
- where recall behaved surprisingly;
- what integration would make it worth trying in a real agent.

## First Issues To Collect

Use early feedback to create issues in these buckets:

- Setup friction: build, bindings, docs, examples.
- API shape: confusing parameters, missing defaults, hard-to-use types.
- Recall quality: stale results, missing important memories, noisy context.
- Re-validation workflow: unclear flags, quarantine, confirmation, promotion.
- Tideline debugger: unclear event replay, missing export needs, visual overload.
- Benchmark credibility: missing baselines, unclear metrics, weak datasets.
- Security posture: poisoning concerns, read-safety hooks, logging expectations.

## Minimum Feedback Template

```text
What were you trying to build?
Which surface did you use? Rust / Python / Node / server / Tideline
What worked?
What failed or felt unclear?
Did Shibahama prevent a stale or repeated-memory failure?
What would make you try it again?
```

## Triage Policy

Treat setup failures and incorrect memory behavior as launch blockers. Treat
feature requests as follow-up unless they expose a core API gap. Do not convert
external benchmark requests into claims until the harness can reproduce them with
logged config and data.
