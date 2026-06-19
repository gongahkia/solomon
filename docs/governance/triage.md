# Triage

Maintainers target a first response within 7 days for public issues and pull requests.

First response means one of:

- confirming the report has enough information
- asking for reproduction details
- assigning an area label
- linking a related issue or RFC
- closing with a reason

Severity can change the response order. Security reports follow `SECURITY.md`, not the public triage SLA.

## Weekly Triage

Weekly triage uses a 15-minute recorded meeting. The calendar source lives at [Triage Calendar](triage-calendar.ics).

Agenda:

- unlabeled issues
- new pull requests
- stale bug reports awaiting reporter input
- performance regressions
- release blockers

The meeting owner records the session or writes timestamped notes when recording is unavailable. Notes should include:

- date
- attendees
- issue and pull request links reviewed
- labels changed
- owners assigned
- release blockers identified
- first-response SLA misses

The first-response SLA check is mechanical: every public issue or pull request without maintainer response after 7 days becomes a triage blocker until it is answered or closed with a reason.

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

Planning labels describe cross-cutting queues:

- `v2/candidate`: candidate for post-v1.0 v2 RFC planning
