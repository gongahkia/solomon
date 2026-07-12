<!-- SPDX-License-Identifier: Apache-2.0 -->

# Prior art reading list

This list identifies adjacent systems and standards; it does not assert that Solomon implements, interoperates with,
or is endorsed by any of them.

## Temporal data and provenance

- [Datomic history](https://docs.datomic.com/pro/overview/history.html) — immutable database values and historical
  reads; useful contrast for event history and “as known then” questions.
- [XTDB bitemporality](https://docs.xtdb.com/intro/what-is-xtdb.html) — system-time plus valid-time data model;
  relevant to Solomon's separate ingestion and valid time.
- [Crux-to-XTDB rename](https://xtdb.com/blog/crux-to-xtdb-rename) — explains the relationship between the names
  used in older bitemporal database material.
- [PostgreSQL temporal constraints](https://www.postgresql.org/docs/current/rangetypes.html) — range types and
  exclusion constraints are a practical relational baseline for temporal validity intervals.

## Citators and legal knowledge systems

- [Westlaw KeyCite](https://legal.thomsonreuters.com/en/products/westlaw/keycite) — citator workflow for authority
  history and treatment; Solomon is not a replacement for a comprehensive citator.
- [LexisNexis Shepard's](https://www.lexisnexis.com/en-us/products/shepards) — another citator reference point for
  validation and authority treatment.
- [iManage Insight+](https://imanage.com/imanage-products/knowledge-search-management/insightplus/) — governed firm
  knowledge discovery; adjacent to, rather than a substitute for, currency evidence.

## Professional and AI governance

- [ABA Formal Opinion 512](https://www.americanbar.org/content/dam/aba/administrative/professional_responsibility/ethics-opinions/aba-formal-opinion-512.pdf) — US ethics guidance on generative-AI use by lawyers.
- [EU AI Act, Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj) — read Articles 6 and 52 in
  context; applicability depends on system, actor, geography, and timing.
- [Singapore PDPC AI governance](https://www.pdpc.gov.sg/help-and-resources/2020/01/model-ai-governance-framework) —
  governance, accountability, transparency, and human-oversight guidance.

## Host integration

- [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2024-11-05/basic) — protocol
  concepts and transport/session semantics for the interface Solomon exposes to hosts.

## Design boundary

Solomon borrows the need for temporal reconstruction, authority-aware review, and typed host interfaces. Its narrow
claim is different: it records and exposes deterministic currency evidence for internal legal positions. It does not
monitor all authorities, replace external citators, or decide legal correctness.
