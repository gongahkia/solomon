# Contributing to Solomon

Solomon accepts focused bug fixes, repair-pack additions, documentation improvements, tests, and portability work. Read [SECURITY.md](SECURITY.md) before reporting a vulnerability.

## Before opening a pull request

Use an issue form to describe a user-visible bug or repair request. For a small, obvious correction, a pull request may include the problem statement directly.

Never include credentials, access tokens, cookies, private repository URLs, or unredacted terminal logs. Replace sensitive values with clear placeholders before sharing a command or failure output.

Keep one change set to one problem. Preserve Solomon's default model: diagnose locally, explain the proposed repair, and require a user action before execution. Do not add automatic command replay, telemetry, remote inference, or a background service without an explicit design decision.

## Development checks

Go 1.25 or newer is required. Run the project checks before submitting a pull request:

```sh
make ci
make latency-gate
make verify-local
```

`make verify-local` cross-compiles Windows but does not execute Windows runtime tests. The GitHub Windows job runs those tests.

## Repair packs and tests

Packs are declarative data, not executable code. Give each rule a stable lowercase-kebab-case identifier, a risk class, a static rationale, and fixture coverage. A repair that can delete data, change remote state, broaden a path, or contain a secret is high risk and must not be auto-applied.

Add the narrowest regression test that demonstrates the intended behavior. Do not weaken a test, redaction, shell safety check, or runtime guard to accommodate a change.

## Pull request review

Explain the observed behavior, the intended behavior, and the verification you ran. By submitting a contribution, you agree that it is licensed under the repository's Apache-2.0 license unless you state otherwise in writing before submission.
