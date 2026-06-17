# Maintainer Onboarding

This page defines how Shisa grants maintainer access during the BDFL-start phase.

## Eligibility

A maintainer candidate should have:

- a vouched entry in `VOUCHES`
- sustained review or implementation work
- evidence of careful security judgment
- comfort with RFC, benchmark, and test requirements
- no unresolved conduct or trust concern

Vouch status alone is not write access. It is one input to the access decision.

## Access Checklist

Before granting write access:

1. Confirm the candidate's GitHub handle matches `VOUCHES`.
2. Run `shisa vouch verify VOUCHES`.
3. Confirm 2FA is enabled on the GitHub account.
4. Review recent PRs for test quality, scope control, and response to feedback.
5. Record the access decision in the relevant issue or PR.
6. Update `VOUCHES` if the role changes.

## Maintainer Duties

Maintainers are expected to:

- keep changes scoped and reviewable
- require tests or a clear no-test reason
- require benchmark evidence for hot-path changes
- enforce RFC requirements for protocol, plugin API, security, theme, rendering, and governance changes
- reject capability broadening without explicit user-facing rationale
- keep user secrets, local environment data, and plugin trust boundaries central in review

## Access Removal

Write access can be removed for inactivity, repeated review-quality issues, security negligence, or conduct violations. Removal should be recorded publicly unless doing so would expose private safety or conduct details.

## Steering Transition Triggers

Shisa starts with BDFL governance. The transition triggers are:

| Trigger | Action |
| --- | --- |
| 5 active contributors with at least 10 merged PRs each over 12 months | form a 3-person Steering Group by PEP-13-style vote |
| 1,000 GitHub stars and 100 plugin authors | create a marketplace stewardship sub-team |
| either trigger above is reached | bring on a co-maintainer with full commit rights |

The trigger state should be reviewed during maintainer onboarding, release planning, and governance RFC review.

## References

- `docs/governance/vouch.md`
- `rfcs/README.md`
- `north-star.md` section 35
