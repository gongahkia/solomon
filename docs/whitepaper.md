<!-- SPDX-License-Identifier: Apache-2.0 -->

# Solomon: currency infrastructure for verified legal knowledge

## Abstract

Legal knowledge systems usually optimize retrieval. They collect documents, rank passages, and make them available to a
search interface or language model. That solves an important problem, but it leaves a harder operational question
unanswered: is the retrieved proposition still safe to reuse for this matter, at this time, and on what evidence?

Solomon treats that question as a currency problem. A legal proposition is not merely text with an embedding. It is a
versioned internal claim with provenance, validity, dependencies, review history, scope, and an explicit state. The
system records when a proposition was ingested, what it was believed to be valid from, which sources or authorities it
depends on, and which human actions have verified, affirmed, contested, superseded, or pinned it. When a dependency
changes, Solomon propagates a review obligation through the dependency graph rather than silently reusing the old
proposition.

The product is deliberately narrower than a legal-reasoning system. It does not determine the law, resolve conflicts,
or certify compliance. It prepares current, scoped, evidence-bearing internal context for a lawyer or a compatible MCP
host. Its core contract is: flag uncertainty, preserve the route to evidence, and prevent stale knowledge from being
injected as if it were current.

This paper explains that contract through five design elements: a bi-temporal knowledge model, dependency
propagation, deterministic primitives, a fail-closed boundary, and an append-oriented audit chain. Together they make
currency an inspectable operational property rather than an inference hidden in a model prompt.

## 1. The problem: retrieval is not currency

Firms create useful internal material continuously: research notes, template clauses, transaction checklists, house
views, client updates, verification records, and source extracts. Much of it remains useful after its first use. Some
of it becomes inaccurate or unsafe to reuse when a statute changes, a regulator publishes guidance, a court decides a
point, a contract version changes, or a firm revises its position.

A conventional retrieval system can still return the older material because its language is relevant. That is not a
bug in semantic search. Relevance and currency are different dimensions. A concise memo about the right topic may be
the worst possible context if its decisive authority moved last week. A high-quality model can make the situation
worse by restating a stale proposition fluently, obscuring the missing review step.

The operational failure is often not that a system retrieved a document. It is that it removed the distinction between
“this is related” and “this is presently reusable.” A lawyer needs to know the source, the applicable scope, the last
verification, the dependent authority, the reason for any flag, and the person who may resolve it. A host assistant
needs a machine-readable rule for whether it may inject the text into a draft.

Solomon separates these questions. Retrieval finds candidates. Currency evaluates their reuse state. Boundary control
assesses whether content can cross into a model route. Audit records reconstruct the decision. The separation avoids a
single score that attempts to hide legal relevance, source quality, freshness, confidentiality, and human authority
inside an opaque ranking result.

## 2. Knowledge as an evidence-bearing record

The fundamental unit is a `KnowledgeItem`. It represents an internal proposition or source-derived record, not a claim
that the system has decided the legal issue. Each item contains content, a kind, provenance, optional matter and client
scope, and lifecycle information. Kinds distinguish surfaces such as notes, house views, positions, authority
materials, and corrections. Provenance records a source kind and source reference; the associated event history records
the actors and basis for later changes.

The model has three useful layers.

First, a content layer stores the proposition and its scope. Scope matters because a statement that is appropriate for
one client, product, jurisdiction, or transaction may not be reusable elsewhere. Solomon therefore retains matter and
client identifiers and uses them during preflight retrieval. Scope is not a substitute for conflict analysis or ethical
screening, but it prevents a default assumption that all internal knowledge is firm-wide.

Second, a currency layer stores the state required for reuse decisions. The significant states are live,
stale-pending-reverification, superseded, retired, contested, and pinned. “Live” means the item has not been marked
unsafe by the current policy and known dependency state; it does not mean legally correct. “Stale-pending-
reverification” means a dependency or review condition requires a human decision before routine reuse. “Superseded”
preserves the old item while identifying a later successor. “Retired” is intentionally unavailable for ordinary
retrieval. “Contested” preserves the challenge and its proposed correction. “Pinned” is an explicit human decision to
retain a version for a defined use rather than an implicit exception.

Third, an evidence layer records why the state exists. Verification entries may include a reviewer, outcome, basis,
source reference, and time. An authority-change event records the authority identifier, a new version, and the observed
change time. Dependency edges record that an internal item relies on another internal item or an external authority.
The system can therefore return a reason such as: “this position depends on Authority A; Authority A changed to version
B on date C.” The reason is more valuable than a bare warning because it gives a lawyer a review path.

## 3. Bi-temporal reasoning without a false claim of temporal completeness

Legal material has at least two times. Valid time is when a proposition is understood to apply in the external world.
Ingestion time is when the firm recorded or received it. These can differ materially. A court decision may be issued
today but apply to a prior period; a source may have been valid for months before it was added to the firm system; a
firm may discover an earlier error after a client deliverable has been produced.

Solomon retains both dimensions so that queries and audits can distinguish “what did we know then?” from “what was
purportedly valid then?” An item can have a `valid_from` value and an ingestion timestamp. Lifecycle events are also
time-stamped. This design supports point-in-time inspection and prevents a common audit error: treating the latest
database value as if it were the state available at a historic decision point.

Bi-temporal storage does not recreate every legal history automatically. Source versioning, commencement analysis,
retroactivity, jurisdictional publication rules, and the relationship between a source and a firm conclusion remain
substantive work. Solomon records the dates and evidence supplied to it, then makes the assumptions visible. It does
not infer that a new source automatically governs a historic matter merely because it is newer.

This limited claim is important. The system supports reconstruction of its own decision record. It does not claim to
be a complete temporal law database. In practice, a firm should retain canonical source links, source versions,
effective-date analysis, reviewer identity, and the specific matter context alongside any Solomon item. The
jurisdiction notes in this repository describe examples of that source-routing discipline.

## 4. Dependency propagation: changes should travel as review obligations

An internal position is often downstream of several authorities. A transaction checklist may depend on a statute, a
regulator notice, a firm interpretation, and a client contract. If one authority moves, copying a new version into a
repository is insufficient. The firm needs to know which internal positions may require review, which downstream
materials inherit that uncertainty, and whether a model host should still see them as reusable context.

Solomon represents this relationship with typed dependency edges. An edge can link an internal item to an external
authority, one internal item to another, or other supported graph objects. When an authority change is registered, the
propagator finds affected paths and records stale reasons for dependent items. The result is intentionally conservative:
the change does not rewrite legal text or declare the dependent position wrong. It changes the reuse state to
stale-pending-reverification and identifies the dependency that needs review.

This has two useful consequences. First, the system avoids false certainty. A host that calls preflight before drafting
does not receive a stale item as ordinary current context. Second, the review queue becomes prioritizable. A reviewer
can see the changed authority, the impacted positions, the path of dependency, and the scope of each item. This is more
actionable than a generic “knowledge base out of date” notification.

The propagation model also supports explicit conflict handling. A later position may supersede an earlier one, but the
older position remains retrievable through audit paths. A reviewer may contest a proposition and preserve a proposed
correction until it is affirmed. A pin can retain a particular version for a justified workflow. These states make
exceptions visible rather than relying on undocumented local memory.

Propagation is not a proof of materiality. Every dependency edge is a human or system assertion requiring evidence.
The system can suggest potential references, but confirmation remains a curatorial action. The value of the graph is
not that it eliminates judgment; it captures the judgment in a form that can be inspected, challenged, and updated.

## 5. Deterministic primitives as the product boundary

Solomon exposes deterministic primitives instead of a general “answer the legal question” endpoint. Representative
operations include ingest, preflight context, check currency, why, register authority change, contest, affirm, pin,
confirm dependency, and export audit material. Each operation has a narrow input/output contract and an identifiable
effect on state.

This design has several advantages. It keeps the system useful to multiple hosts without making a host model the
source of truth. It permits repeatable tests: the same seeded item, authority change, and dependency graph should
produce the same state transition and explanation. It also lets a firm integrate the primitives into an existing
workflow without accepting a new general-purpose legal chatbot.

The MCP surface is the primary integration mechanism. A compatible host can request current context before drafting,
inspect currency for a candidate item, or retrieve a `why` trace. The host remains responsible for its final output.
Solomon's job is to return only context whose state permits reuse under the configured policy, together with enough
metadata to make uncertainty explicit.

Determinism is not merely an engineering preference. In a legal workflow, a reviewer needs to reproduce why an item was
withheld or made available. A probabilistic retrieval-only control may be useful as an aid, but it is difficult to audit
when its reason changes from run to run. Solomon therefore keeps model-assisted work at the edges: reference
suggestions may be generated, but a human confirms the relation; a host may draft text, but the currency gate decides
which verified internal context is presented to it.

## 6. The boundary: model access is a separate decision

Currency does not answer whether data may leave a firm-controlled workflow. Solomon therefore includes a boundary
subsystem for ingestion and model-bound context. The boundary reviews text for lexical PII, MNPI, special-category,
identifier, cross-border, and handling markers; it supports pseudonymization, anonymization, opaque redaction,
reidentification through volatile mappings, and document metadata scrubbing.

The boundary is fail-closed for designated failures. If a boundary review or pseudonymization call cannot be completed,
the relevant ingestion or model-egress operation is refused rather than silently bypassed. Raw-text model egress
requires an explicit per-matter opt-in. Mappings used for reidentification are held in volatile memory and removed after
the operation. These controls reduce uncontrolled context flow, but they do not prove that a prompt has no protected
information or that a vendor is safe.

Jurisdiction profiles select a common detector baseline plus strict terms and identifier patterns for Singapore,
Malaysia, the United Kingdom, and the European Union. The profile is a routing control, not a compliance switch. It
sets default source and destination packs for API, MCP, console, and selected CLI flows. Each profile is tested to
preserve the common baseline; it cannot decide legal classification, lawful basis, privilege, consent, transfer
validity, or whether a fact is legally inside information.

This separation is intentional. A system should not claim that a model route is safe because a document is current, or
that a document is current because it passed a lexical privacy check. Currency, permission, and professional review are
different controls. A responsible deployment records all three.

## 7. Audit chain and evidence packs

Operational trust depends on reconstruction. Solomon writes audit events for material lifecycle actions and can verify
the journal chain. The journal is append-oriented: later actions do not erase the fact that an earlier position was
ingested, verified, contested, or superseded. An audit pack can collect relevant records, dependencies, state reasons,
and supporting output for a review.

The audit record is designed to answer concrete questions: what item was used; what was its state; which authority or
internal item affected it; when did the change occur; who performed the review action; what basis was recorded; and
what did the system provide to the host? It is not a substitute for a legal file, legal professional privilege analysis,
or a regulator's required record. It is evidence about Solomon's own workflow.

Auditability also improves engineering discipline. A feature that cannot explain its state transition is difficult to
test and dangerous to expose to a model host. By requiring event records and `why` traces, the system makes state
changes reviewable by design. The same evidence supports debugging, internal quality assurance, client governance
questions, and post-incident analysis.

## 8. An end-to-end workflow

Consider an internal banking memorandum that relies on an external authority. A lawyer or curator ingests the memo
with source reference and matter scope. The boundary reviews the text; if policy quarantines it, the item is retained
with the quarantine reason rather than being treated as normal reusable knowledge. The curator confirms a dependency
edge from the memo to the authority. A reviewer records a verification basis.

Later, the authority changes. A curator registers the change with a source version and observed date. Solomon finds the
dependent memo, marks it stale-pending-reverification, and records the authority path. A host asks MCP for preflight
context for the relevant matter. The stale memo is not injected as current context. The host may call `check_currency`
or `why`, receive the dependency reason, and present a bounded message such as “the firm's prior view depends on an
authority that moved; re-verification is required before reuse.”

A lawyer then reviews the source. They may affirm the existing proposition with a new basis, create a successor,
contest it pending correction, retire it, or pin a version for a documented purpose. Each path is a deliberate state
transition. The next preflight reflects that state rather than relying on prompt wording or a hidden manual checklist.

The demonstration scenarios in this repository exercise this shape with fictional data. They are not claims about a
real vendor, law firm, or current law. Their value is that the propagation and context-withholding behavior are
repeatable headlessly and covered by tests.

### 8.1 Integration patterns

The simplest integration is a pre-draft gate. A host receives a user request, identifies matter and client scope, and
calls `preflight_context`. Solomon returns scoped items that are eligible for ordinary reuse under the policy, together
with state and source metadata. The host uses only that result for its internal-context prompt. If preflight is empty,
the host should say that no current firm context is available and route the request to review; it should not substitute
an older search result because the answer feels incomplete.

A second pattern is a reviewer cockpit. A curator uses the console or API to inspect stale queues after a source
change. The relevant work is not bulk drafting. It is checking the change, reading dependency paths, assigning review,
and recording an outcome. The console is intentionally secondary to the MCP surface, but its value is to make the
human state transitions visible enough to operate. A well-designed review queue shows the affected item, scope,
authority change, prior verification, owner, and reason rather than asking a reviewer to reconstruct them from raw
documents.

A third pattern is audit-first reporting. A practice lead or client-governance function can request a currency report
for a matter, client, practice area, or period. The report should be treated as a record of knowledge governance: what
moved, what was reviewed, what remains stale, and what evidence supports those facts. It is not a privileged-work
product by default and does not determine whether any disclosure is appropriate. Its usefulness depends on the
firm's retention, access, and report-review controls.

A fourth pattern is change intake. A team monitoring authorities can register a source change without attempting to
write a legal summary into every downstream document. The change event triggers a deterministic impact query. The team
then prioritises the affected items according to matter, client, practice, risk, or deadline. This pattern is
particularly useful when the content library is large: the graph identifies the possible review set, while lawyers
decide which conclusions actually change.

These patterns share a common discipline: hosts call the currency primitive before they reuse internal material, and
humans retain authority for interpretation. Solomon does not need to be the destination interface for every user. It
can sit behind an existing drafting assistant, document workflow, service API, or reviewer console as the component
that answers whether a particular item is eligible to be treated as current firm context.

### 8.2 Failure modes and recovery

A reliable knowledge workflow must define failure behavior before an incident. If the boundary is unavailable during
ingestion or model sanitisation, Solomon fails closed for those operations. A deployment should surface that condition
clearly, preserve enough non-sensitive diagnostics for operators, and provide a manual review path. Failing open would
turn an outage into uncontrolled knowledge or data reuse; silently retrying without visibility could hide a material
gap in the audit record.

If a dependency edge is missing, the system may fail to flag a downstream item. This is why edge confirmation and
curatorial review are central. A firm can recover by adding the edge, registering or replaying the authority change,
and reviewing the resulting impact set. If an edge is too broad, the system may over-flag material. That is generally a
safer failure, but it still has cost: reviewers may lose trust if every source change produces an unusable queue. The
remedy is better edge evidence and narrower, better-scoped knowledge items, not suppressing stale states without a
recorded basis.

If a reviewer affirms an item incorrectly, Solomon preserves the decision basis and actor so that a later challenge
can be investigated. The system cannot independently detect a legal error merely because the event chain is valid. If
an internal conclusion is contested, the contest flow prevents the proposed correction from silently becoming a live
position. If a successor is created, the older item remains available through audit history rather than being deleted.
These recovery paths are designed to make correction possible without rewriting the past.

Model-host failures also require discipline. A host may ignore the preflight contract, add its own stale material, or
make a final legal assertion unsupported by the supplied context. Solomon can record what it returned, not what an
external host actually chose to say unless the integration records that separately. Production integrations should
therefore log host invocation identifiers, prompt templates or policy version, selected item identifiers, and the
final human approval path where appropriate. Those controls belong to the host and deployment architecture, but they
are necessary to connect a currency decision to an end-user artifact.

### 8.3 Why this is infrastructure rather than a citator clone

Citators and legal research systems answer whether primary authorities have received subsequent treatment. Document
management systems answer where firm documents are stored. General RAG systems answer which text resembles a query.
Solomon is complementary: it records a firm's internal proposition, its dependencies, lifecycle state, and review
evidence, then supplies the current subset to compatible hosts. It does not need to replace a citator's authority
coverage, a document management system's permissions, or a research platform's editorial analysis.

This narrower position prevents a common procurement mistake. A firm may buy excellent search and still lack a
reliable workflow for tracking whether its own reusable positions should be revisited after an authority moves. It may
also have a strong document management system but no machine-readable state that tells an assistant whether a memo is
eligible for prompt injection. Currency infrastructure occupies that gap: it connects source movement, internal
knowledge, review action, and model context without claiming to be the source of legal truth.

The product boundary is therefore intentionally conservative. It is useful only if it makes the existing professional
workflow more explicit, reviewable, and resistant to silent stale reuse. If an integration asks it to make a legal
decision, hide uncertainty, or bypass a boundary control, that request is outside the system's design.

## 9. Deployment and governance boundaries

### 9.1 State semantics and review policy

Currency state needs a policy context. A firm may reasonably impose different review cadence for a standard internal
note, a transaction-specific house view, a high-stakes regulatory position, and a client-facing deliverable. Solomon's
verification policy provides configurable maximum ages and a high-stakes path, but the policy is not a universal legal
standard. It is a machine-enforceable expression of a firm's review appetite. A short maximum age is not proof of
quality; a long maximum age is not proof of negligence. The useful question is whether the policy is explicit,
consistently applied, and reviewable against the work type.

The state machine also makes negative information useful. A stale-pending item should not disappear from all
operational views, because a lawyer may need to understand that a prior view exists and why it is withheld. Preflight
excludes it from default model context, while currency and audit surfaces can still show the title, scope, stale reason,
and verification path. This avoids two bad defaults: silently reusing stale content, or hiding its existence so
completely that a reviewer repeats prior work unnecessarily.

Different state transitions have different implications. An authority change is evidence that a dependency moved, not
evidence that every downstream conclusion is wrong. It therefore causes a stale-pending state. A supersession is a
human or workflow statement that a newer item replaces an older one for ordinary reuse. A contest is a challenge that
preserves a proposed correction but does not silently rewrite the original. A pin is an explicit exception that should
carry a reason and be visible in audit. Treating these as separate concepts prevents an operational team from using a
single generic “obsolete” flag for fundamentally different situations.

The system is designed to fail toward review rather than autonomous correction. That is appropriate where changes can
be legally material but their consequence depends on a client fact pattern, transitional provisions, a contract, or an
area outside the source's direct scope. A human reviewer can affirm the original item after examining the change; the
resulting verification basis then becomes new evidence. The machine's role is to preserve the obligation and the route
to evidence until that decision occurs.

### 9.2 Graph design and bounded propagation

Dependency graphs can become unreliable if they are treated as an automatic citation extractor. Solomon therefore
distinguishes suggested edges from confirmed edges. A reference extractor may identify potential authorities or
internal relationships in a note, but a curator confirms the edge before it is relied on for propagation. The confirmed
edge records type, direction, source, target, and relevant metadata. A review team can then inspect the graph rather
than trusting an unreviewed text match.

Propagation should also be bounded operationally. Large graphs can contain broad sources with thousands of downstream
items. The product needs deterministic traversal and performance controls so that registering one change remains
predictable, while the review queue remains meaningful. Solomon's benchmarks measure dependency propagation at
increasing graph sizes, and the implementation reports impact paths rather than only a count. Performance is not a
substitute for judgment: a faster traversal that omits downstream paths would make the system look current while
losing the evidence needed for review.

Graph edges are not claims about legal hierarchy. An edge may say an internal memo depends on an external authority,
that one position is derived from another, or that a newer position may supersede an earlier item. The semantics are
deliberately operational. They tell the currency engine which state changes may need to travel. Whether the cited
authority actually controls a matter remains a legal analysis performed and recorded outside the edge itself.

This distinction makes the graph usable across practices. Corporate, banking, employment, and dispute teams can model
different relationships without forcing all content into a single ontology of law. The shared minimum is modest: an
item, a dependency, a source identity, a state, and a reason. Firms can layer richer classification and matter-specific
metadata on top without weakening the core currency contract.

### 9.3 Evaluation strategy

Evaluation must test the product's actual claim. A benchmark that measures only retrieval relevance would not prove
that a stale item is withheld. Solomon therefore exercises several layers. Unit and property tests cover lifecycle
transitions, dependency behavior, stale reasons, boundary operations, and placeholder handling. Scenario tests seed
fictional firms or vendors, register authority changes, and assert that stale items are absent from model-bound
preflight context. Currency-report and audit-pack tests exercise reviewer-facing evidence rather than only API output.

The jurisdiction coverage suite is similarly limited but useful. It tests configured lexical detector families and
specific identifier examples across selected profiles. It does not claim statutory completeness or detector accuracy in
the wild. The point of the test is regression prevention: a new profile must not weaken baseline detection, and a
jurisdiction-specific pattern must remain tied to its route. A false-positive/false-negative evaluation program would
need real, authorised corpora and governance that are outside this repository's portfolio scope.

Human evaluation remains necessary. The early reviewer prompts in this project ask lawyers whether stale explanations
are understandable, whether edge evidence is sufficient to trust a dependency, whether matter/client reports answer
governance questions, and what proof they need for boundary confidence. Those are product questions that cannot be
answered by a green test suite. The system can prove that it emitted a `why` trace; only an accountable reviewer can
say whether that trace supports a defensible workflow.

### 9.4 Data minimisation and retention in practice

The boundary architecture should be read as a minimisation aid, not as a data-retention policy. A deployment still
needs an inventory of the text sent to the boundary, the text returned to a model host, the vendor's logging and
training terms, backups, support access, encryption, access control, retention windows, deletion procedures, and
cross-border transfers. A local-only route limits one class of exposure but does not answer all of those questions.

Solomon intentionally separates volatile reidentification mappings from its durable audit data. A mapping is required
to restore placeholders in a permitted response, but retaining it as a normal knowledge record would create a new
identity store. The implementation holds mappings only for the immediate round trip and flushes them after use.
Auditable metadata can say that a boundary process occurred without storing the original identity mapping in the audit
pack. The exact evidence retained remains a firm policy decision and may vary by matter.

The same discipline applies to authority material. A canonical source link and version identifier are often more useful
for currency than copying large source texts into every internal note. Where source content must be retained, a firm
should preserve the version, license, access record, and any relevant publication status. Solomon can associate that
evidence with an item; it should not encourage bulk collection merely because a retrieval system can index it.

Solomon is useful only when its deployment constraints are clear. A local SKU is offline-default and uses SQLite and
the in-process boundary. A server SKU adds API-key authentication, tenant isolation, optional Postgres storage, and
configured remote model routing. Neither mode removes the firm's responsibility to validate model vendors, access
control, retention, transfer, client engagement terms, conflicts, supervision, or incident response.

The curator console is a secondary operational surface. It supports verification queues, dependency suggestions,
audit-pack viewing, and currency reports. The CLI and FastAPI surface enable automation and service integration. MCP
is the primary host-facing surface. This ordering matters: the system's value is the verified-currency contract, not a
claim to replace existing document management, practice management, research, or drafting products.

Governance should define who can ingest material, confirm dependencies, affirm positions, apply pins, and access audit
packs. It should specify what source records are required, how quickly authority changes are assessed, how conflicts
are escalated, and when a matter must be routed to a qualified lawyer. Solomon can retain the evidence of those
decisions; it cannot supply the authority structure by itself.

## 10. Limitations and conclusion

Solomon does not decide the law. It does not validate the completeness of a dependency graph, authenticate a source,
resolve a conflict, determine legal privilege, guarantee data protection, or certify a model route. Lexical boundary
detection has false positives and false negatives. A live state is a statement about the system's known currency
conditions, not a guarantee of substantive correctness. Jurisdiction notes are research aids, not legal opinions.

Those limitations are a design feature rather than an omission. A legal knowledge system should expose the boundary
between machine-recorded evidence and professional judgment. Solomon's contribution is a disciplined substrate for
that judgment: bi-temporal records, explicit lifecycle states, dependency-driven review obligations, deterministic
operations, fail-closed boundary control, and reconstructable audit evidence.

The result is not “AI that knows the law.” It is infrastructure that helps a firm avoid treating old, unscoped, or
insufficiently reviewed internal knowledge as silently current when a human or an MCP host needs to act on it.
