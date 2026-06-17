# Triage

Maintainers target a first response within 7 days for public issues and pull requests.

First response means one of:

- confirming the report has enough information
- asking for reproduction details
- assigning an area label
- linking a related issue or RFC
- closing with a reason

Severity can change the response order. Security reports follow `SECURITY.md`, not the public triage SLA.

Weekly triage should review:

- unlabeled issues
- new pull requests
- stale bug reports awaiting reporter input
- performance regressions
- release blockers

## Labels

Every public issue and pull request should have one `kind/*`, one `area/*`, and one `priority/*` label once triaged. The canonical label manifest lives at `.github/labels.yml`.

Kind labels describe the work shape:

- `kind/bug`
- `kind/perf`
- `kind/feat`
- `kind/docs`
- `kind/rfc`
- `kind/plugin`

Area labels describe ownership:

- `area/core`
- `area/cloud`
- `area/ai`
- `area/vcs`
- `area/plugins`
- `area/shell`
- `area/docs`
- `area/ci`
- `area/release`
- `area/security`

Priority labels describe scheduling:

- `priority/p0`: release blocker or active security issue
- `priority/p1`: high-priority bug or near-term roadmap work
- `priority/p2`: normal priority
- `priority/p3`: backlog or opportunistic work
