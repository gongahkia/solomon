# Security Policy

## Supported Versions

Shisa has not shipped a stable release yet. Security fixes target `main` until the first release branch exists.

## Reporting a Vulnerability

Report suspected vulnerabilities privately to angryapplegravy@gmail.com.

Include:

- affected commit or version
- platform and shell
- reproduction steps
- impact
- whether the issue is already public

Do not open a public issue for an unpatched vulnerability.

## Sandbox Bounty Pool

Sandbox escape reports are eligible for the pool defined in [Bug Bounty](docs/governance/bug-bounty.md). Payouts require a private reproducible report and available restricted bounty funds.

## Scope

In scope:

- Lua sandbox escapes
- undeclared plugin capability access
- daemon socket spoofing or cross-user access
- malformed frame crashes or memory corruption
- supply-chain verification bypasses
- update/signature verification bypasses once implemented
- prod_guard bypasses caused by Shisa policy bugs once implemented

Out of scope:

- social engineering
- denial-of-service requiring local shell access only
- bugs in third-party shells, terminals, or VCS tools
- vulnerabilities in user-authored plugins not distributed by Shisa
- missing hardening for features not implemented yet, unless a stub creates real exposure

## Disclosure

The project aims to acknowledge reports within 7 days. Security fixes should include tests or a written reason tests are not possible.

Public advisories will avoid publishing exploit details until a fix is available.
