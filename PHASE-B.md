# Phase B — ContinuityBench: Epistemic-Governance Eval (The Wedge)

Referenced by `NEXT-TODO.md` items 28–33.

## Purpose

This is where Shibahama wins rather than ties. The agent-memory field benchmarks
conversational recall (LoCoMo/LongMemEval) but openly admits it does **not**
evaluate what happens *after* retrieval: when two memories contradict, which
wins; when a fact becomes stale, is it detected and superseded; does confidence
track the quality of the evidence. Those are exactly Shibahama's mechanisms
(credence, bi-temporal valid-time, non-destructive supersession, usage-driven
significance).

ContinuityBench measures those properties, framed in the language of the chosen
audience — **coding agents and framework builders**. The unit of difficulty is
not "did you remember a fact from session 1" but "a fact CHANGED across sessions;
do you answer with the current truth or a stale one, and can you show why."

## Critical guardrail (non-negotiable)

Engram (`arXiv:2606.09900`) is the closest published competitor: bi-temporal
memory, non-destructive supersession, provenance chains, LongMemEval-S claims.
**Do not write any claim that Shibahama beats Engram (or anyone) until a
checked-in artifact proves a stale-rate, auditability, or token-cost win on a
matching continuity slice.** If Shibahama does NOT beat the baselines, the honest
result gets committed and the positioning adjusts. A null result here is a valid,
publishable outcome — see `docs/null-hypothesis.md`. This phase's job is to
produce *measured truth*, not a marketing number.

## Deliverables (definition of done)

1. `ContinuityBench` dataset: a versioned, documented, hashable set of continuity
   tasks (not the 12 hand-built CurrencyBench queries — a real, larger set).
2. A runner that evaluates any system implementing the adapter interface and
   emits per-metric JSON + Markdown under `benchmarks/results/continuity/`.
3. Committed results for: Shibahama, a flat/warehouse baseline, full-context
   (where reproducible), and at least one real external system (Mem0 OSS;
   Engram if runnable).
4. A Tideline view that shows a stale answer being avoided, with the `why` trace.
5. A sub-60-second `examples/` demo of a stale coding fact being superseded.

## The dataset

### Task anatomy

Each task is a timeline of **events** followed by a **query** asked at a
**query-time**. The core mechanic: at least one fact is *established*, then
*superseded* by a later event. The correct answer depends on reading valid-time
correctly.

```json
{
  "task_id": "rename-signature-0007",
  "category": "supersession",
  "domain": "coding",
  "events": [
    {
      "t": "2026-01-05T10:00:00Z",
      "content": "Function `fetch_user(id: int) -> User` added to api/users.py",
      "provenance": {"kind": "file", "ref": "api/users.py", "corroboration": 1},
      "establishes": "fetch_user_signature"
    },
    {
      "t": "2026-02-10T09:00:00Z",
      "content": "Function renamed: `fetch_user` -> `get_user`, now async, returns Optional[User]",
      "provenance": {"kind": "file", "ref": "api/users.py", "corroboration": 2},
      "supersedes": "fetch_user_signature",
      "establishes": "get_user_signature"
    }
  ],
  "query": {
    "t": "2026-03-01T12:00:00Z",
    "text": "What is the current signature of the user-fetch function?",
    "target_fact": "get_user_signature"
  },
  "answers": {
    "current": "async get_user(id: int) -> Optional[User]",
    "stale": "fetch_user(id: int) -> User"
  }
}
```

The `answers.stale` field is essential: it's the *trap*. A system that retrieves
the original, un-superseded fact returns `stale`. The stale-answer rate is the
fraction of queries where the system surfaces `stale` instead of `current`.

### Categories (each gets its own metric emphasis)

1. **supersession** — a fact changes; current truth must win over the prior
   version. (Drives stale-answer rate.)
2. **contradiction** — two memories conflict *without* a clean temporal ordering
   (e.g. two sources disagree at overlapping valid-time, different credence). The
   system must surface the higher-credence / better-corroborated one. (Drives
   contradiction-resolution accuracy.)
3. **evidence-quality** — facts established with varying provenance strength
   (single uncorroborated mention vs repeatedly corroborated vs human-affirmed).
   Tests whether credence tracks evidence. (Drives credence-tracks-evidence.)
4. **stable-recall (control)** — a fact is established once and never changes;
   the query just needs plain recall. This is the control set where flat RAG
   should tie or win — including it is what makes the eval honest rather than
   home-turf-rigged.

### Coding-agent framing (domain = "coding")

Construct tasks from realistic coding-agent memory pain:
- API signature renamed / re-typed across sessions (supersession)
- A dependency version bumped, changing behavior (supersession)
- Two files implying different conventions (contradiction by credence/recency)
- A design decision reversed in a later session (supersession)
- A TODO comment vs the actual implemented behavior (contradiction)
- A function documented once vs referenced+corroborated many times
  (evidence-quality)

Also include a smaller `domain: "general"` slice (personal facts that change —
job, city, preference) so the eval isn't coding-only and can be cross-read
against LoCoMo-style tasks in Phase C.

### Size & rigor

- **Minimum 120 tasks** total to be more than anecdotal; target ~200. Distribute
  roughly: 40% supersession, 25% contradiction, 20% evidence-quality, 15%
  stable-recall control.
- Each task fully specified in JSON; the dataset is one or more JSON files under
  `benchmarks/continuity/dataset/`.
- Compute and commit a **dataset hash** (sha256 of the canonicalized JSON). Every
  result file references the hash it was run against.
- Document task provenance: are these hand-authored, templated, or
  LLM-generated-then-human-reviewed? State it plainly. If LLM-assisted, a human
  must review every task and that's recorded. Do not pretend hand-authored if
  templated.

## Metrics (exact definitions)

These definitions are the spec — implement them precisely; do not improvise
scoring.

### 1. Stale-answer rate (lower is better)
Over all `supersession` tasks: `stale_count / total`, where a query is "stale" if
the system's returned/ranked-top context contains the `stale` answer fact and not
the `current` fact. If both appear, it counts as stale unless `current` is ranked
strictly above `stale` (the system surfaced current truth first). Report the
ranking rule used.

### 2. Contradiction-resolution accuracy (higher is better)
Over all `contradiction` tasks: fraction where the system's top-ranked relevant
memory is the one the task marks as authoritative (higher credence / better
corroboration / more recent valid-time, per the task's `resolution` field). Each
contradiction task must specify which side is correct and why.

### 3. Credence-tracks-evidence (correlation, higher is better)
Over all `evidence-quality` tasks: Spearman rank correlation between each item's
assigned credence/significance (as the system reports it) and the task's ground-
truth evidence-strength ordinal (1=single uncorroborated … 4=human-affirmed).
Report ρ and n. This tests whether the system's confidence is *calibrated* to
evidence, the property the field doesn't measure.

### 4. Retrieval token cost (lower is better)
Mean tokens of context the system returns per query to answer it. This is the
economics axis — a continuity win is an economics win before a raw-accuracy win.
Count tokens with a stated tokenizer (e.g. `tiktoken cl100k_base`) and report the
tokenizer. For flat/full-context baselines this number is large by design;
that's the point.

### 5. Stable-recall accuracy (control, higher is better)
Over `stable-recall` tasks: plain recall correctness. Report it for every system.
Expect flat RAG to tie or win here — reporting that is the honesty mechanism.

## Adapter interface

Every evaluated system implements one Python interface so the runner is
system-agnostic:

```python
class MemorySystemAdapter(Protocol):
    def reset(self) -> None: ...
    def ingest(self, event: dict) -> None:      # apply one timeline event
        ...
    def query(self, q: dict) -> QueryResult:    # returns ranked contexts + tokens
        ...

@dataclass
class QueryResult:
    contexts: list[str]          # ranked, best-first
    item_credences: list[float]  # parallel to contexts where available, else []
    token_count: int             # tokens the system would feed the LLM
```

Adapters to build:
- **ShibahamaAdapter** — drives the real engine (via the Python binding once Gate
  0 item 17 lands; until then, in-process Rust harness). Ingest replays events as
  `write()` with the event's valid-time and provenance; supersession events use
  the `correct`/invalidate path so valid-time is set correctly. NOTE: this
  depends on Gate 0 item 20 (stored graph wired into recall) and item 19 (recency
  weight on) being resolved — a contradiction/recency task is meaningless if
  recency weight is 0.
- **FlatRetrievalAdapter (warehouse)** — embed every event, return top-k by cosine
  similarity, no supersession logic. The honest baseline (not the strawman that
  scores 0 — this one should actually win the stable-recall control).
- **FullContextAdapter** — concatenate all events into context, let the judge
  read it. Reproducible and a strong baseline; high token cost by design.
- **Mem0Adapter** — self-hosted Mem0 OSS. Minimum credible external anchor.
- **EngramAdapter** — if runnable from the paper's release; if not, document the
  attempt and omission. Do not claim a win over a system you didn't run.

## Scoring / judging

For correctness metrics that need semantic matching (did the returned context
contain the `current` fact?), use exact/substring match against the task's
`answers.current` / `answers.stale` fact strings first. Only where that's
insufficient, use an LLM judge with a fixed prompt, fixed model, and the judge
prompt committed to the repo. Record judge model + prompt hash in every result.
Prefer deterministic matching wherever the task design allows it — design tasks
so the fact strings are matchable.

## Result artifacts

Under `benchmarks/results/continuity/`, one file per system:

```json
{
  "manifest": {
    "system": "shibahama",
    "dataset_hash": "sha256:...",
    "model": "<judge/embedding model>",
    "seed": 0,
    "tokenizer": "cl100k_base",
    "judge_prompt_hash": "sha256:...",
    "commit": "...",
    "command": "...",
    "timestamp_utc": "..."
  },
  "metrics": {
    "stale_answer_rate": 0.0,
    "contradiction_resolution_acc": 0.0,
    "credence_tracks_evidence_rho": 0.0,
    "credence_n": 0,
    "mean_retrieval_tokens": 0,
    "stable_recall_acc": 0.0
  },
  "by_category": { "...": {} },
  "per_task": [ { "task_id": "...", "answer": "current|stale", "tokens": 0 } ]
}
```

Plus a generated `SUMMARY.md` cross-tabulating all systems × all metrics, with a
plain-language reading of where Shibahama wins, ties, and loses. The "loses"
column must be present and filled.

## Tideline integration (item 32 — the headline DX moment)

A view that replays one supersession task and *shows the resolution*:
- the superseded item (greyed / marked stale) and the current item, side by side
- the valid-time intervals on a timeline
- the credence of each, and which one recall surfaced and why (the `why` trace)
- the token cost of Shibahama's answer vs the full-context baseline's

This is the legible version of contradiction resolution that no competitor has.
It reads from the same engine state as the existing `why`/`audit`/`bitemporal`
views — reuse them, don't build parallel plumbing.

## Demo (item 33)

`examples/coding_agent_staleness.py` (or `.ts`): under 60 seconds, an interviewer
runs it and watches: ingest the `fetch_user` signature → ingest the rename to
`get_user` → query "current signature?" → Shibahama returns `get_user`
(current), the flat baseline returns `fetch_user` (stale), and the `why` trace
explains the supersession. One screen of output, no setup beyond the quickstart.

## Acceptance criteria

- [ ] Dataset ≥120 tasks, hashed, with documented authorship/provenance and the
      four categories present in roughly the target distribution.
- [ ] Runner evaluates all five adapter types (Engram allowed to be a documented
      omission if unrunnable) and emits the JSON + SUMMARY.md.
- [ ] All five metrics computed per their exact definitions above.
- [ ] `SUMMARY.md` includes the "where Shibahama loses" column, filled honestly.
- [ ] Stable-recall control is present and flat RAG's win/tie there is reported,
      not hidden.
- [ ] No claim of beating Engram (or anyone) exists in repo docs unless a
      committed artifact supports it on a matching slice.
- [ ] Tideline staleness-resolution view renders from real engine state.
- [ ] Sub-60s coding-staleness demo runs from a clean quickstart.

## Sequencing note

Phase B depends on Gate 0 items **19** (recency weight on) and **20** (stored
graph in recall) being resolved, and is far stronger after item **15** (double-
penalty fix) since contradiction penalties feed contradiction-resolution scoring.
Do Gate 0 first.
