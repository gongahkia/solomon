<!-- SPDX-License-Identifier: Apache-2.0 -->

# FAQ

## Isn't this just iManage?

No. A DMS stores, secures, and retrieves work product. Solomon records whether a firm position remains usable:
dependencies, supersession, verification, contestability, and audit evidence. It is designed to complement, not
replace, document management or permissions.

## Why not Harvey?

Harvey is a legal AI workspace. Solomon is not a drafting or research assistant; it exposes deterministic currency
and evidence primitives to an MCP host. A host may use Solomon before it reuses internal firm knowledge. See the
[positioning comparison](./positioning.md).

## What about retention?

Solomon's audit journal is metadata-only, and boundary mappings are volatile after reidentification. Those design
choices do not determine a firm's retention, legal-hold, privilege, DMS, model-provider, or deployment obligations.
Validate the complete data path before processing client information. See
[Boundary and memory](https://github.com/gongahkia/solomon#boundary-and-memory).

## What about ABA Formal Opinion 512, SRA, and PDPA?

They remain firm and lawyer responsibilities. ABA Formal Opinion 512 identifies competence, confidentiality,
communication, supervision, candour, and fees as relevant to generative-AI use; the SRA calls for appropriate human
review and professional judgement of AI-assisted output; the PDPC's AI guidance emphasises governance, accountability,
transparency, and human oversight. Solomon can produce review and audit evidence, but it does not establish compliance
or replace legal judgement. See the [duties map](./duties-map.md) and the official [ABA opinion](https://www.americanbar.org/content/dam/aba/administrative/professional_responsibility/ethics-opinions/aba-formal-opinion-512.pdf), [SRA supervision guidance](https://www.sra.org.uk/solicitors/guidance/effective-supervision-guidance/), and [PDPC AI governance guidance](https://www.pdpc.gov.sg/help-and-resources/2020/01/model-ai-governance-framework).

## Why MCP?

MCP gives a host a narrow, typed interface for preflight context, currency checks, impact, explanations, and audit
packs. The host remains responsible for its prompts, model, tools, and final work product; Solomon supplies the
currency decision and evidence rather than an opaque prompt plugin.

## Why not LLM-only RAG?

RAG can identify relevant text, but relevance does not establish whether that text is current. Solomon retains the
state needed to derive currency deterministically: dependency movement, verification, supersession, retirement, and
contestability. See [Why currency, not search](./why-currency-not-search.md).

## Does Solomon decide the law?

No. It flags changed dependencies and overdue review. Lawyers decide whether a position survives and whether a final
work product is correct.
