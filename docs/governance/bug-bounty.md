# Bug Bounty

This policy defines the Shisa sandbox-escape bounty pool.

## Status

The pool is active for valid private reports when restricted bounty funds exist. If the pool balance is zero, reports remain in scope but have no payout attached.

## Funding

Accepted funding sources:

- GitHub Sponsors funds marked for `sandbox-bounty`
- Open Collective funds marked for `sandbox-bounty`
- maintainer-approved security grants marked for `sandbox-bounty`

Restricted bounty funds are reserved for bounty awards, payment fees, and tax/accounting costs tied to awards. General sponsorship funds do not become bounty funds unless the published spending summary labels the transfer.

## Scope

Eligible reports demonstrate one of these behaviors in current `main` or a supported release:

- Lua plugin code reaches removed globals such as `os`, `io`, `package`, `debug`, `require`, `dofile`, or `loadfile` without an explicit safe wrapper.
- Lua plugin code bypasses manifest capability checks for filesystem, env, exec, network, secrets, or pre-exec access.
- The local `require` wrapper loads code outside the configured plugin root.
- Lua plugin code disables or bypasses CPU or memory limits in a way that preserves host API access.
- A plugin package or manifest bypass lets untrusted code run before trust or capability review.

Out of scope:

- denial of service without host API access or data exposure
- attacks requiring an already-compromised user account
- social engineering
- terminal, shell, Git, LuaJIT, or OS bugs without a Shisa policy bypass
- behavior allowed by a capability the user explicitly trusted
- vulnerabilities in third-party plugins not distributed or verified by Shisa

## Awards

Award class is based on impact and reproducibility:

| Class | Impact |
| --- | --- |
| Critical | arbitrary command execution or secret exfiltration from a default-deny plugin |
| High | undeclared filesystem, env, network, secrets, or pre-exec access |
| Medium | sandbox bypass requiring uncommon config or partial capability confusion |
| Low | hardening gap with no demonstrated access beyond documented capability behavior |

Award amounts depend on the public pool balance at triage time. Maintainers should publish the balance, award class, and anonymized report summary after a fix is available.

## Reporter Rules

- Report privately through `SECURITY.md`.
- Include affected commit, platform, plugin code, reproduction steps, and observed impact.
- Avoid reading secrets, persisting access, or touching network targets outside reporter-owned systems.
- Do not publish details until maintainers release a fix or agree to disclosure.

## Recognition

Reporters can opt in to public credit. Hall-of-fame entries list reporter name, award class, affected area, and fixed version or commit.
