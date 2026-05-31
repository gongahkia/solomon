# Decorum

Browser extension. Renders Community-Notes-style annotation under LinkedIn posts. Visual is the hook — must feel exactly like X's "Readers added context they thought people might want to know." Same card, same typography rhythm, same restraint.

## Why this works
- Instant recognition. Users mentally import the credibility of X Community Notes.
- LinkedIn has no native countervoice. Replies are sycophantic. Reactions are positive-only.
- Virality vector: screenshot of a cringe post + the note underneath. Self-distributing.

## What goes in the note
Two parallel tracks, same card:
1. **Tonal flag** — waffle, humblebrag, sycophancy, engagement-bait, AI-ghostwritten, corporate-cliché, fake-vulnerability. One-line reason.
2. **Factual context** — when the post makes a checkable claim (funding round, hiring number, "first to X", citation of a study), retrieve and annotate. This is where the cool tech lives.

## Cool-tech stack
- **Exa** (or Perplexity Sonar / Tavily) for fast web retrieval on factual claims. Exa's neural search fits — query "did $company raise $X in $month" and get cited results without scraping.
- **Anthropic Haiku 4.5** first pass: classify claim type, decide if retrieval is warranted. Cheap, fast.
- **Sonnet 4.6** second pass for borderline tonal calls + synthesis of retrieved evidence into note copy.
- **Prompt caching** on the rubric + few-shot examples → high hit rate, static prompt.
- **Local SQLite** (lifted from Swee-SG Shield pattern) for audit trail: every note has trace ID, replayable.
- **MV3 extension**, content script reads `.feed-shared-update-v2` DOM nodes, side-panel for settings + ledger.

## UX rules (do not violate)
- Note appears *under* the post, not as a popup or overlay. Match X exactly.
- "Readers added context" header, identical wording.
- Confidence threshold gate — no note shown below ~0.75. Empty > noisy.
- One note per post. Never multiple.
- User can "rate this note" → feeds a quiet eval loop.

## Honesty surface
- Public ledger of false positives, same prominence as hits. Lifted from WhaleMirror's "show losses equally" posture.
- Per-note "why flagged" trace expandable inline.

## Open questions (park for next session)
- LinkedIn ToS exposure for content scripts that decorate the feed. [Inference] likely tolerated for personal extensions but unclear at scale.
- Retrieval cost per active user — Exa pricing × notes/day × user count. Needs a back-of-envelope before commit.
- Do we let users contribute notes (real Community Notes model) or keep it fully AI? Hybrid risks moderation cost; pure-AI risks libel exposure on factual claims.
- Auth/backend: serverless (Cloudflare Workers + D1) vs reuse Swee-SG REST gateway shape.
- Naming. "LinkedIn Community Notes" is descriptive but X owns the brand association. "Receipts," "Sidebar," "Footnote" candidates.

## Reuse from existing repos
- Swee-SG `apps/web` Radix + Framer for the note card component. [Inference] ~20% of the work.
- Swee-SG Shield audit/SQLite for the trace ledger.
- Swee-SG REST gateway shape if not going serverless.
- Everything `sg_*` and Pulse: drop.
- Stonks-CLI: nothing structural, just the ledger-honesty posture.

## First milestone (when picking back up)
1. Standalone repo, MV3 skeleton, content script that just logs detected post nodes.
2. Static-mock note card under one hardcoded post — prove the visual lands.
3. Wire Haiku for tonal classification on real posts (no retrieval yet).
4. Add Exa for the first factual-claim category (funding announcements — narrow + high-signal).
5. Ship to 5 friends as unpacked extension before any backend.
