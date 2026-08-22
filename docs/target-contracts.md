# Target contracts

Shisa is a local target-contract verifier for direct infrastructure commands. It compares an expected target with the inputs the child process would use immediately before that child starts.

It does not switch a Kubernetes context, write credentials, set `TF_WORKSPACE`, parse arbitrary shell scripts, or enforce anything on a cluster or cloud account. Use a context activator such as `ctx`, `kubectx`, `direnv`, or `aws-vault` for activation; use cloud IAM, Kubernetes admission control, and Terraform backend controls for enforcement.

## User stories

### Kubernetes operator in two terminals

Mina works on staging and payments production in parallel. Her runbook invokes:

```sh
shisa target run payments-prod -- kubectl delete deployment api
```

Shisa resolves the effective context, namespace, and cluster server from `kubectl config view`, compares those values against `payments-prod`, and refuses to spawn `kubectl` if any configured field is missing or different. An explicit `--context` or `--namespace` is included in the calculation. An explicit `--kubeconfig` is rejected in this first release rather than silently guessed.

### Terraform/OpenTofu operator in the wrong workspace

Rowan has opened the intended repository but their terminal has `TF_WORKSPACE=staging` while the release runbook expects production:

```sh
shisa target run payments-prod -- tofu apply
```

Shisa observes `TF_WORKSPACE` first, then `.terraform/environment` or local state. It refuses before `tofu` starts when the workspace differs. The inspection also reports a local state-lock file, but a lock is diagnostic information—not a remote-lock guarantee.

## Configuration

The only default configuration path is user-owned, not project-local:

```text
~/.config/shisa/targets.toml
```

```toml
[contracts.payments-prod.kubernetes]
context = "payments-prod-admin"
namespace = "payments"
cluster_server = "https://cluster.prod.example"

[contracts.payments-prod.terraform]
workspace = "production"
```

Contract names accept letters, numbers, `_`, and `-`. The parser intentionally supports only the fields above. This avoids treating an arbitrary repository configuration file as a source of execution policy or credentials.

## Commands

```sh
shisa target list
shisa target inspect payments-prod
shisa target inspect payments-prod --json
shisa target run payments-prod -- kubectl --context payments-prod-admin -n payments get pods
shisa target run payments-prod -- terraform plan
```

`run` only accepts a direct `kubectl`, `helm`, `terraform`, or `tofu` executable. It does not accept `sh -c`, aliases, wrappers, or release scripts because Shisa cannot inspect the eventual target they select. This is a safety boundary, not a missing shell integration.

Each inspection reports `expected`, `observed`, a source, and one of `verified`, `mismatch`, `unknown`, or `not_configured`. A `run` proceeds only when the target relevant to the executable is `verified`.

## Limits

Kubernetes context names and Terraform workspaces are local client inputs. A verified result proves only that the local invocation matches the configured contract at that boundary. It does not prove cloud account identity, authorization, remote backend selection, cluster admission outcome, or a script's later behavior. Those checks belong in the infrastructure control plane.
