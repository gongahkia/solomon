# Solomon — deterministic-primitive reasoning, contestability, and multi-jurisdiction EU-AI-Act documentation

These are ADDITIVE on top of the current fix-list (Kaypoh wiring etc.). Implement
Parts 1 and 2 as first-class features. Document Part 3 thoroughly. Preserve the
ethos: flag-don't-adjudicate, never-delete, credence (ModelInferred never
outranks FirmAuthoritative), and the Kaypoh boundary on the default path.

## Part 1 — Deterministic primitives + the call-plan AS the audit trail (first-class)
Context: independent 2026 research ("Deterministic Legal Agents", arXiv:2510.06002)
arrives at exactly Solomon's thesis — shift from probabilistic retrieval to
agent-driven inquiry built on DETERMINISTIC PRIMITIVES, where the agent's plan
itself becomes a human-readable audit trail, for regulated domains needing
precision, auditability, and historical correctness. Make this Solomon's explicit
architecture.

1. Treat the existing verbs (`recall`, `evaluate_currency`, `impact_query`,
   `timeline`, `record_verification`, `why`) as a CANONICAL DETERMINISTIC PRIMITIVE
   API. Each primitive: deterministic given store state, no hidden LLM call,
   fully logged (inputs, outputs, store version/timestamp).
2. The LLM NEVER decides currency or supersession directly. It may only emit a
   PLAN — an ordered sequence of primitive calls — which Solomon executes
   deterministically. The model proposes; the primitives dispose.
3. Implement a plan executor: takes an LLM-proposed plan, validates each step is a
   known primitive with valid args, executes deterministically, and records the
   full plan + each result as the audit trail for that query.
4. `why(answer)` must reconstruct the exact primitive call-plan that produced an
   answer — this IS the explainability artifact. A reviewer/regulator can read the
   plan and re-execute it to the same result (determinism = reproducibility).
5. Tests: same plan + same store state → identical results (determinism); the
   executor rejects any step that isn't a sanctioned primitive (no arbitrary LLM
   side-effects); the recorded plan re-executes to the same answer.

## Part 2 — Contestability as a first-class verb (first-class)
Context: 2026 XAI/governance guidance repeatedly names CONTESTABILITY — humans
must be able to challenge an output, trace it to sources, and correct the system.
Solomon half-has this via the verification step; make it explicit and make the
contest improve the store.

6. Add `contest(item_id, lawyer_id, reason, proposed_correction?)`:
   - Records an append-only audit event (who, when, why).
   - Lowers the item's effective credence / flags it for partner review.
   - If a correction is proposed, it enters at LOWER credence, quarantined; on
     confirmation by a FirmAuthoritative actor, it supersedes (invalidate-not-
     delete) the prior version.
   - A contest is itself a currency signal — it can trigger StalePending
     Reverification on the contested item and (via the dependency graph) its
     dependents.
7. Add `affirm(item_id, lawyer_id)` (partner re-affirms → refresh verification,
   raise credence) and `pin(item_id)` (set credence floor — firm-authoritative
   positions that must not decay).
8. Contestability must respect roles: only a FirmAuthoritative actor's affirm can
   promote a contested correction to authoritative. ModelInferred contests can
   flag but never override a human-affirmed position.
9. Surface contests in the audit chain and in recall output (a contested item is
   returned with its contest history visible — never silently).
10. Tests: contest lowers credence + emits audit event + never deletes; proposed
    correction routes through quarantine→authoritative-confirm→supersede; a
    contest propagates staleness to dependents; role rules enforced.

## Part 3 — EU AI Act / multi-jurisdiction regulator-ready evidence (document heavily)
Context: EU AI Act full enforcement opens 2 Aug 2026; Art. 13 requires high-risk
systems to provide interpretable explanations of how outputs were produced. The
audit chain (currently framed as privilege defense) should be documented as
GENERAL regulator-ready evidence, multi-jurisdictional.

11. Add `docs/regulatory-evidence.md`:
    - Reframe the audit chain as regulator-ready evidence generation, not only
      privilege defense. Map Solomon's artifacts (provenance, currency state,
      verification record, the deterministic call-plan from Part 1, contest
      history from Part 2) to what regulators ask: "what did the system do, why,
      on what basis, who was accountable."
    - EU AI Act Art. 13 explainability: show how the deterministic call-plan
      satisfies "interpret outputs / understand how decisions were made."
    - Multi-jurisdictional: do NOT hard-code to the EU. Document how the same
      evidence model maps to other regimes (e.g. NIST AI RMF, ISO/IEC 42001, and
      — reuse Kaypoh's existing 18-jurisdiction statute framing — note that the
      evidence chain is jurisdiction-agnostic while the *substantive* rules differ).
      Be explicit that Solomon provides the evidence structure, not legal advice.
12. Add a short README section: "Regulator-ready by construction" — every answer
    carries a reproducible plan + provenance + currency + contest history.
13. Keep the flag-don't-adjudicate honesty: documentation must state Solomon
    produces EVIDENCE about its own reasoning and currency, and does NOT certify
    legal compliance or decide the law.

## Reconcile the TODO
14. Add Parts 1–2 as honest, accurately-checked phases; add Part 3 as documentation
    tasks. Don't over-check. Annotate partials truthfully.

## Report back
The primitive-plan executor + determinism/reproducibility test results; the
contest/affirm/pin verbs + tests + how contests propagate via the dependency
graph; and the regulatory-evidence doc (confirm it's multi-jurisdictional and
keeps the flag-don't-adjudicate stance).
