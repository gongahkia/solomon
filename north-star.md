# Shisa — North Star

> A local target contract for direct infrastructure commands.

This document is the source of truth for scope. A change that contradicts it must update this document in the same patch.

## One-line pitch

**Verify the target your process will use before it starts.**

Shisa compares a named, user-owned contract with the local state that a direct Kubernetes or Terraform/OpenTofu invocation will consume. It shows expected values, observed values, their provenance, and an explicit verdict. `shisa target run` starts only a verified direct command.

## Core contract

The first release supports two target domains:

| Domain | Expected fields | Observed from | Verdict means |
| --- | --- | --- | --- |
| Kubernetes | context, namespace, cluster server | `kubectl config view` plus explicit command flags | the local client configuration selected by this invocation matches the contract |
| Terraform/OpenTofu | workspace | `TF_WORKSPACE`, then `.terraform/environment` or local state | the local workspace input matches the contract |

Every field is reported as `verified`, `mismatch`, `unknown`, or `not_configured`, with a source. A relevant `unknown` blocks `run`; Shisa does not guess.

The configuration lives in `~/.config/shisa/targets.toml`, never in a repository by default. Contracts name an intended target; they never hold credentials or executable policy.

## Scope boundary

Shisa is **not**:

- a shell prompt, shell hook, daemon, theme engine, module framework, benchmark suite, or plugin host;
- a profile/context activator, environment manager, credential vault, VPN/SSH manager, or cloud account switcher;
- a generic command parser, destructive-command guard, command repair tool, or agent runtime;
- a replacement for Kubernetes admission control, cloud IAM/SCPs, Terraform backend locks, or CI policy.

It neither mutates global configuration nor injects target variables into the child. Tools that activate a context remain the source of activation; infrastructure controls remain the source of enforcement. Shisa's responsibility stops at accurately verifying local process inputs before a constrained direct executable starts.

## UX principles

1. **Truth over labels.** `prod` is a name, not evidence. Verify an effective context, namespace, cluster endpoint, or workspace.
2. **Fail closed on uncertainty.** A missing `kubectl`, unresolvable context, unsupported `--kubeconfig`, or missing workspace is `unknown`, not a pass.
3. **No hidden activation.** Inspection must not alter the command environment or global tool configuration.
4. **Small command boundary.** Direct `kubectl`, `helm`, `terraform`, and `tofu` only. Arbitrary scripts and shell strings cannot be truthfully verified in v1.
5. **Local and inspectable.** No daemon, telemetry, network call, credential storage, or background cache is necessary for a check.

## Credible user stories

1. A Kubernetes operator working in staging and production terminals runs `shisa target run payments-prod -- kubectl delete deployment api`. Shisa catches a wrong context, namespace, or cluster endpoint before `kubectl` starts.
2. An infrastructure operator with `TF_WORKSPACE=staging` runs a production OpenTofu release command. Shisa reports the environment variable as the source, shows the mismatch, and refuses before `tofu` starts.

The tool does not promise more than these local checks. A checked command can still be denied, redirected, or altered by its provider, backend, server policy, or downstream script.

## Success criteria

Shisa is useful only if an operator can answer, with a single local command, “what target will this direct invocation use, why does Shisa believe that, and will it be started?” The answer must be reproducible from the config and current local state without relying on a decorative prompt label.

Initial evidence of value is use in shared runbooks and aliases for high-consequence direct commands, not prompt-theme breadth, benchmark charts, or plugin count.
