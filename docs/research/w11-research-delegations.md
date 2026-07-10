# W11 Research Delegations

Checked: 2026-07-10

Scope: issue #15, tasks R1-R22. Sources are public only. `[Inference]`
marks Solomon-specific conclusions. `[Unverified]` marks a requested fact not
confirmed by a captured primary source in this pass. `[No access]` marks a page
that was probed but unavailable from this environment.

## Executive Read

- MCP distribution should target the official MCP Registry first; a separate
  Anthropic-curated legal directory review checklist was not found.
- Singapore/UK/US practice guidance consistently points to confidentiality,
  verification, client communication, competent supervision, and auditability.
- Vendor products cluster around drafting, retrieval, connectors, and workspace
  automation. [Inference] Solomon's sharper wedge remains internal knowledge
  currency, audit packs, and stale-authority preflight before model use.
- The Damien Charlotin database has explicit stale-like categories. A curated
  subset is in `docs/research/stale-authority-cases.json`.
- [Inference] Solomon's valid-time plus event-log model is consistent with
  bitemporal literature, though Solomon is a pragmatic subset, not a full
  temporal DBMS.

## R1 MCP Directory Submission

The official MCP Registry describes itself as an app-store-like list of MCP
servers. Publishing uses an `mcp-publisher` CLI, namespace ownership checks, and
GitHub/DNS/HTTP verification. The current registry is preview/frozen v0.1, not
final GA.

[Inference] Solomon should keep `solomon-mcp.json` aligned with the registry
schema, publish there first, and treat Anthropic directory placement as a later
partner/channel task. [Unverified] No public Anthropic legal-directory review
criteria were captured.

Sources: <https://github.com/modelcontextprotocol/registry>,
<https://modelcontextprotocol.io/specification/2025-06-18>,
<https://code.claude.com/docs/en/mcp>.

## R2 Singapore PDPA And PDPC AI Advisory

PDPA is current on Singapore Statutes Online as at 2026-04-17. Relevant headings
include compliance, policies/practices, consent, purpose limitation,
notification, access/correction, accuracy, protection, retention, cross-border
transfer, and notifiable data breach duties. PDPC's AI governance page remains
the official AI-governance entry point.

[Inference] Solomon's boundary review, zero-egress mode, scoped audit journal,
and redaction-first workflows support PDPA-aligned operational controls but do
not replace legal advice or a firm's PDPA compliance program.

Sources: <https://sso.agc.gov.sg/Act/PDPA2012>,
<https://www.pdpc.gov.sg/organisations/resources/guidance-by-topic/singapores-approach-to-ai-governance>.

## R3 MAS FEAT And MAS Notices

[No access] MAS FEAT, Notice 626, and Notice 637 official URLs returned MAS
maintenance content from this environment. The pages were probed:

- <https://www.mas.gov.sg/publications/monographs-or-information-paper/2018/feat>
- <https://www.mas.gov.sg/regulation/notices/notice-626>
- <https://www.mas.gov.sg/regulation/notices/notice-637>

[Inference] If Solomon is positioned for financial-institution legal work, FEAT
maps naturally to explainability/auditability; Notice 626/637 relevance depends
on matter type and should not be claimed without fresh MAS source access.

## R4 LawSoc Singapore And AGC Guidance

The Law Society of Singapore advisory dated 2026-04-02 warns that public AI
tools may expose lawyers to professional-conduct breaches, especially
confidentiality. It recommends reviewing terms, using enterprise/paid tools when
appropriate, not uploading privileged/confidential/personal data to public tools,
proper anonymisation/redaction, reviewing data-retention/model-training defaults,
and checking cybersecurity safeguards.

AGC/SSO provides canonical Singapore legislation pages, statuses, timelines, RSS
feeds, and current/repealed/uncommenced categories.

Sources: <https://www.lawsociety.org.sg/law-society-advisory-on-the-use-of-publicly-available-ai-tools-pdf-link/>,
<https://sso.agc.gov.sg/>.

## R5 UK SRA And ICO AI/Data Protection

ICO has a current AI and data-protection guidance hub covering AI/data
protection, explanation, auditing tools, and risk toolkits. [Unverified] A
current SRA AI guidance page was not captured; a previously known SRA archived
URL redirected to a 404 during this pass.

[Inference] For UK positioning, cite ICO for data-protection controls and do not
claim SRA-specific AI guidance until a current SRA source is verified.

Sources: <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/>,
<https://www.sra.org.uk/solicitors/resources-archived/artificial-intelligence/>.

## R6 Harvey Vault

Harvey's public site presents Vault as secure document storage, organisation,
and bulk analysis. It also advertises Knowledge and Ecosystem surfaces that
ground answers in trusted sources. Public docs did not expose a detailed
internal-precedent retrieval API.

[Inference] Harvey validates demand for internal-document grounding, but public
material does not show Solomon's currency engine/audit-pack semantics.

Source: <https://www.harvey.ai/>.

## R7 iManage Insight+ API Surface

The requested `imanage.com/products/insight-plus/` URL returned iManage's 404
page. The current official product navigation exposes "Knowledge Search &
Management" and describes helping organisations unlock collective knowledge.
[Unverified] No public Insight+ "Knowledge Discovery & Matter Analytics" API
surface was captured.

Sources: <https://imanage.com/products/insight-plus/>,
<https://imanage.com/imanage-products/knowledge-search-management/>.

## R8 Thomson Reuters/Anthropic CoCounsel MCP Shape

Public reports state Anthropic released legal tools with 20+ MCP connectors and
12 plugins, including integrations with Thomson Reuters/LexisNexis-like legal
platforms. Business Insider reported Thomson Reuters working with Anthropic on
"deep research" inside CoCounsel. [Unverified] No primary public integration
spec or tool schema was captured.

[Inference] Treat the integration shape as connector-based context retrieval and
task automation, not as proof of a public CoCounsel MCP API.

Sources: <https://www.techradar.com/pro/anthropic-reveals-a-host-of-new-legal-tools-for-claude-including-12-new-plugins>,
<https://www.businessinsider.com/anthropic-exec-ai-tools-boost-replace-software-products-2026-2>.

## R9 FastMCP Vs Official MCP SDK

The existing local survey remains the implementation reference: use the official
`mcp` Python SDK, pinned `<2`, because it includes `mcp.server.fastmcp.FastMCP`
and avoids adding standalone FastMCP until needed.

Source: `docs/research/python-mcp-sdk.md`.

## R10 Bitemporal DB State Of Art

Temporal literature separates valid time from transaction time. SQL:2011 covers
application-time and system-versioned tables. XTDB v2 documents automatic
history, SQL:2011 bitemporal capabilities, `VALID_TIME`, `SYSTEM_TIME`, and
`FOR PORTION OF VALID_TIME`. Datomic documents immutable datoms, serialized
transactions, complete audit history, and `as-of`/history reads. PostgreSQL
exposes row-version metadata such as `xmin`, but does not itself provide a full
bitemporal product surface. [Unverified] Crux-specific docs were not captured;
treat it as a follow-up or XTDB-lineage check before making Crux claims.

[Inference] Solomon is consistent with the literature because authority/position
validity is represented separately from ingestion/audit time. It is not a full
replacement for XTDB/Datomic-style query semantics.

Sources: <https://en.wikipedia.org/wiki/Temporal_database>,
<https://en.wikipedia.org/wiki/Valid_time>,
<https://en.wikipedia.org/wiki/Transaction_time>,
<https://docs.xtdb.com/about/time-in-xtdb.html>,
<https://docs.datomic.com/datomic-overview.html>,
<https://www.postgresql.org/docs/current/ddl-system-columns.html>.

## R11 Damien Charlotin Stale-Authority Subset

The AI Hallucination Cases database was last updated 2026-07-09 and listed
1,734 cases in the downloaded CSV during this pass. The public category counts
include `Outdated Advice`, `Overturned Case Law`, and `Repealed Law`; the CSV
contained 33 rows with stale-like signals.

The demo/benchmark subset is in `docs/research/stale-authority-cases.json`.

Source: <https://www.damiencharlotin.com/hallucinations/>.

## R12 Stanford HAI Legal Hallucination Benchmarks

The Stanford-linked legal hallucination work provides two useful evaluation
anchors. `Large Legal Fictions` measures hallucination on random federal case
questions and reports 58%-88% rates across general LLMs. `Hallucination-Free?`
preregisters an evaluation of leading AI legal research tools and reports
17%-33% hallucination rates for tested proprietary tools.

[Inference] Solomon benchmarks should not copy these tasks verbatim. The right
translation is stale-surface, impact-query recall, time-to-flag, and evidence
pack completeness for firm knowledge currency.

Sources: <https://arxiv.org/abs/2401.01301>,
<https://arxiv.org/abs/2405.20362>.

## R13 Prior Art For Internal Currency Engine

Captured prior art clusters:

- Harvey: internal documents, research, and trusted-source grounding.
- iManage: knowledge search/management.
- Legora: collaborative legal AI, context/knowledge, monitors, portal, Word and
  Outlook add-ins.
- Spellbook: Word-based contract review/drafting and precedent search.
- Microsoft Copilot: Graph/federated connectors and permission-aware retrieval.
- CaseFacts: temporal validity and legal fact checking.

[Inference] The wedge is not "legal RAG." The defensible wedge is firm-internal
currency: a trust/check layer that records why internal positions are stale,
which matters are impacted, and what evidence pack a lawyer can audit. [Inference]
This wedge appears under-marketed rather than impossible, but the confidence is
medium because private vendor APIs/roadmaps are not visible.

Sources: <https://www.harvey.ai/>, <https://legora.com/>,
<https://spellbook.com/>, <https://arxiv.org/abs/2601.17230>.

## R14 Singapore Statutes Online And AGC E-Gazette

SSO exposes canonical legislation pages with current/repealed/uncommenced
categories, legislative timelines, print/PDF/Word exports, amendment RSS feeds,
and stable Act URLs. [Unverified] No separate public AGC e-Gazette API was
captured.

[Inference] Solomon should store SSO URLs, Act/chapter identifiers, version
dates, and amendment-feed links as canonical authority references.

Source: <https://sso.agc.gov.sg/>.

## R15 Legora + iManage Partnership

Legora's official site describes a legal AI operating system with data and
integrations, context/knowledge, monitors for regulatory change, portal, and
Office add-ins. Business Insider says Legora Portal competes with legacy legal
file-sharing systems, including iManage Share. [Unverified] No May-2026
Legora+iManage expanded-partnership source was captured.

Sources: <https://legora.com/>,
<https://www.businessinsider.com/legal-ai-startup-legora-client-portal-2025-11>.

## R16 Spellbook Word Add-In

Spellbook publicly positions itself as AI contract review/drafting in Word, with
redlines in Word, preferred precedent drafting, and search across signed deals.
[Inference] MCP-style preflight is plausible before a draft/review action:
retrieve matter/contract context, check stale precedent, then return scoped
warnings. [Unverified] Spellbook public pages do not prove an MCP API.

Source: <https://spellbook.com/>.

## R17 Microsoft Copilot Connector Model

Microsoft distinguishes synced connectors, which index external data into
Microsoft Graph, from federated connectors, which can use MCP to fetch data in
real time without indexing. Microsoft also states Copilot responses respect
source permissions and can cite internal/external sources; Work IQ remains in
the Microsoft 365 trust boundary.

[Inference] Solomon's M365 shape is a federated MCP connector for currency
preflight and audit-pack retrieval, not a bulk indexing connector by default.

Sources: <https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/overview>,
<https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/overview>.

## R18 Duties Map

See `docs/duties-map.md`.

## R19 Adjacent OSS Trust/Check Layers

Useful analogies:

- Dependabot alerts/reviews: dependency graph plus update/security checks.
- Snyk: developer-facing vulnerability and dependency risk checks.
- in-toto: supply-chain step provenance and integrity metadata.
- Sigstore: signing and transparency infrastructure.
- SLSA: provenance/build-process assurance.
- License-compliance tooling: policy checks over dependency/license metadata.

[Inference] Solomon should position as the legal-KM analogue: a preflight trust
layer over knowledge dependencies, not a drafting model.

Sources: <https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain>,
<https://snyk.io/>, <https://in-toto.io/>,
<https://github.com/sigstore/sigstore>, <https://arxiv.org/abs/2409.05014>.

## R20 Bitemporal Modelling In Legal Informatics

Snodgrass/Ahn introduced valid/transaction-time framing; later temporal-DB work
and SQL:2011 formalised valid/system-versioned tables. CaseFacts explicitly
models temporal legal validity using Supported/Refuted/Overruled labels against
Supreme Court precedent.

[Inference] Solomon applies bitemporal modelling to legal KM by separating legal
validity of positions/authorities from the firm's audit/ingestion history. No
primary source captured a directly equivalent law-firm KM currency engine.

Sources: <https://en.wikipedia.org/wiki/Valid_time>,
<https://en.wikipedia.org/wiki/Transaction_time>,
<https://arxiv.org/abs/2601.17230>.

## R21 CoCounsel / Westlaw KeyCite Supersession

Thomson Reuters' KeyCite page says it checks whether cases, statutes,
regulations, and administrative decisions remain good law; provides citing
references, history, alerts, red/yellow/blue-striped flags, and Overruling Risk.
It says Overruling Risk warns when a point of law is implicitly undermined based
on reliance on invalid prior decisions. [Unverified] Internal representation is
not public.

Source: <https://legal.thomsonreuters.com/en/products/westlaw/keycite>.

## R22 Anthropic Legal Program Contact

Public Anthropic/MCP routes captured here are product/docs routes, not a legal
program application process. [Unverified] No specific Anthropic legal program
contact or partnership process was found. Research only; no outreach performed.

Sources: <https://code.claude.com/docs/en/mcp>,
<https://github.com/modelcontextprotocol/registry>,
<https://www.anthropic.com/contact-sales>.
