# Early-User Outreach Tracker

Actual outreach is blocked until a release owner supplies target recipients and
approves sending from the appropriate account. Use this tracker to keep the
first wave small and concrete.

## Status

| Wave | Audience | Owner | Send Status | Feedback Issues |
| --- | --- | --- | --- | --- |
| 1 | Coding-agent maintainers with multi-session project context | TBD | Blocked: needs recipient list | None yet |
| 1 | Internal support/ops agent builders with changing facts | TBD | Blocked: needs recipient list | None yet |
| 1 | Agent-memory evaluators who can run local benchmarks | TBD | Blocked: needs recipient list | None yet |
| 1 | Security-minded users evaluating stored-memory poisoning risk | TBD | Blocked: needs recipient list | None yet |

## Send Checklist

- Pick 5-10 recipients who already have long-lived memory pain.
- Send the message from `docs/launch/early-users.md`.
- Link directly to the README, CurrencyBench docs, and the early-user feedback
  issue template.
- Ask for one concrete attempted workflow, not general impressions.
- Convert every response into either `feedback`, `bug`, `enhancement`, or
  `benchmarks` issues.

## Intake Query

Use this GitHub issue search to review collected feedback:

```text
repo:gongahkia/shibahama label:feedback
```

Setup failures and incorrect memory behavior are launch blockers. Benchmark
requests become claims only after the harness can reproduce them with checked-in
config and result artifacts.
