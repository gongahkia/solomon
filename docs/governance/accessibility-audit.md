# Accessibility Audit

Shisa tracks accessibility review separately from security review.

## Pre-1.0 Audit

Before v1.0, commission a one-time external accessibility audit covering:

- `--a11y` prompt output
- screen-reader labels from `render --explain-a11y`
- shell init behavior with `SHISA_A11Y=1`
- keyboard-only CLI flows
- built-in `a11y` theme contrast and ASCII fallback
- OSC 9183 accessibility summary behavior once implemented

Do not mark the audit complete until findings and remediation notes are published.

## Annual Re-Audits

After the pre-1.0 audit, run an annual re-audit. The calendar source lives at [Accessibility Audit Calendar](accessibility-audit-calendar.ics).

Annual re-audit scope:

- new prompt modules
- new shell hooks
- changes to glyph/color fallback
- changes to risk, exit-status, prod, SSH, and cloud-context wording
- regressions found by VoiceOver, NVDA, Orca, or other assistive-tech testing
- unresolved findings from the prior audit
