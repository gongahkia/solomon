# Shisa

Shisa verifies the effective local target immediately before a direct Kubernetes or Terraform/OpenTofu command starts.

It is not a prompt, context manager, credential broker, command corrector, or remote policy engine. Those are separate product categories with established tools. Shisa fills the smaller gap between “I intended to operate on production” and “what will this process actually use?”

## What it does

You declare a named target contract in a user-owned config file:

```toml
[contracts.payments-prod.kubernetes]
context = "payments-prod-admin"
namespace = "payments"
cluster_server = "https://cluster.prod.example"

[contracts.payments-prod.terraform]
workspace = "production"
```

Then inspect or gate a direct tool invocation:

```sh
shisa target inspect payments-prod
shisa target run payments-prod -- kubectl delete deployment api
shisa target run payments-prod -- tofu apply
```

Before it launches the child, Shisa reports or compares the local values that matter:

- Kubernetes context, namespace, and cluster server from `kubectl config view`, including explicit context and namespace flags.
- Terraform/OpenTofu workspace from `TF_WORKSPACE`, then `.terraform/environment` or local state.
- Source and current observation status: `verified`, `mismatch`, `unknown`, or `not_configured`.

It refuses to launch when the target relevant to the command is anything other than `verified`.

## What it deliberately does not do

- Switch or activate contexts. Use `ctx`, `kubectx`, `direnv`, and provider credential tooling for that.
- Accept arbitrary scripts, wrappers, aliases, or `sh -c`. Those can select a target after Shisa's check. `run` is limited to direct `kubectl`, `helm`, `terraform`, and `tofu` invocations.
- Treat labels such as `prod` as proof, retrieve cloud credentials, or replace cloud-side authorization/admission controls.
- Render a shell prompt, run a daemon, import prompt themes, host plugins, classify destructive commands, or correct shell commands.

See [target contracts](docs/target-contracts.md) for the user stories, format, commands, and limits.

## Build

Requires Zig `0.15.2`.

```sh
zig build test
zig build release
./zig-out/bin/shisa --help
```

The default config path is `~/.config/shisa/targets.toml`; `--config PATH` is available for explicit automation and testing.

## Product boundary

Shisa verifies local process inputs at one invocation boundary. A successful check does not prove cloud identity, authorization, a Terraform remote backend, or the outcome of a Kubernetes API request. Enforce those properties in the infrastructure control plane.

## License

MIT. See [LICENSE](LICENSE).
