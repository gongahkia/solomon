# Cloud and Infrastructure Profiles

Shisa ships cloud context as supported core configuration, not as a marketplace package. Initialize one of the bounded profiles:

```sh
shisa init --defaults --profile cloud
shisa init --defaults --profile infra
```

Both profiles retain the quiet primary prompt. They show operational context only while composing relevant commands, keeping normal repository work uncluttered.

| Profile | Triggered commands | Context shown |
| --- | --- | --- |
| `cloud` | `aws`, `az`, `gcloud`, `helm`, `kubectl` | local cloud identity, risk tier, SSO freshness, SSH target |
| `infra` | cloud commands plus `terraform`, `tofu` | `cloud` context plus local IaC workspace, region drift, VPN, and container provenance |

`context-rich` remains available for compatibility, but it renders the full local module set continuously and is not the recommended operating mode.

## Support contract

- The profile uses built-in modules; it does not load a plugin, search a registry, or require a capability grant.
- `cloud_ctx` reads local provider configuration and caches GCP, Azure, and Kubernetes display values in the daemon. It does not contact provider APIs.
- `cost_glance` is deliberately absent from both profiles. Its refresh workflow is separately opt-in because it can invoke a cloud CLI.
- Cloud cache fixture tests and the `shisa context` API expose cache state and generation. Consumers can distinguish `unknown`, `pending`, `ready`, and `stale` instead of treating an absent value as safe.
- The normal release process owns signing and distribution; profiles do not have an independent bundle or signing channel. See [release security](release-security.md).

When a risk tier needs explanation, use the same classifier exposed to the prompt:

```sh
shisa cloud explain api-prd-use1
```

It prints the tier, source, and matching rule. This is an explanation of classification, not a policy decision or an authorization check.

To explain whether the command-aware panel itself should be visible, including a hidden result, run:

```sh
shisa explain --command 'kubectl get pods'
```

The result names the safe executable, target, selected modules, and the configuration rule that matched (or the reason the panel is hidden).

## Deliberate boundaries

The profile is local-first, not a cloud control plane. It does not refresh SSO credentials, query current cost, store secrets, or enforce organizational policy. `prod_guard` remains a typed-confirmation safety rail; it is bypassable by design.
