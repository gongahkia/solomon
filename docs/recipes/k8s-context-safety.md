# k8s Context Safety in 60 Seconds

Show the active Kubernetes context in the prompt, classify risky names, and gate destructive commands in zsh, bash, or fish.

## 1. Render Kubernetes context

Add `cloud_ctx` and `risk_tier` to the prompt module list:

```toml
version = 1
theme = "plain"

[prompt]
modules = ["cwd", "git_branch", "cloud_ctx", "risk_tier", "exit_status"]

[modules.cloud_ctx]
kubernetes = true
```

`cloud_ctx` reads the first `KUBECONFIG` path, or `~/.kube/config`, and shows Kubernetes context and namespace in the `cloud[...]` segment.

## 2. Tune risk names

Add local rules when cluster names do not match the defaults:

```toml
# ~/.config/shisa/risk_tiers.toml
prod = ["prod", "production", "*-prd-*"]
staging = ["stg", "staging", "*-preprod-*"]
dev = ["dev", "sandbox", "kind-*"]
```

Check a context name:

```sh
shisa cloud explain api-prd-use1
```

Higher-risk matches win when more than one cloud context is present.

## 3. Enable pre-exec guard

Enable the guard in a shell hook that supports pre-exec checks.

```sh
export SHISA_PROD_GUARD=1
```

```fish
set -gx SHISA_PROD_GUARD 1
```

With the daemon running, destructive Kubernetes commands such as `kubectl delete` and `kubectl drain` are sent to `shisa cloud preexec`. When the current tier is `prod`, the CLI requires typing `prod` before proceeding.

## 4. Audit

Review destructive pre-exec decisions:

```sh
shisa cloud audit
```

The request audit log lives at `~/.local/state/shisa/cloud_requests.jsonl`; destructive decisions live at `~/.local/state/shisa/prod_guard.jsonl`.

See [Config Schema](../config-schema.md), [Risk Tiers](../risk-tiers.md), [Prod Guard](../prod-guard.md), and [Shells](../shells.md).
