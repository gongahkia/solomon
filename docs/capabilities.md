# Plugin Capabilities

Plugin capabilities are deny-by-default. A missing field grants no host access.

| Capability | Type | Risk | Safer scope |
| --- | --- | --- | --- |
| `fs_read` | path list | Leaks local files, tokens, kubeconfigs, SSH config, repo contents. | Exact files or narrow `/**` scopes. Prefer config files over home-directory globs. |
| `fs_watch` | path list | Reveals file activity patterns and can increase watcher pressure. | Exact config/state files. Avoid recursive repo or home watches. |
| `exec` | command allow-list or `false` | Runs host commands; can leak env, hang, or mutate state. | Fixed binary names only. No shells, package managers, or interpreters by default. |
| `net` | provider/domain allow-list or `false` | Sends local context off-host and can block prompt work. | Provider ids only, explicit user trust, async-only use. |
| `secrets` | bool | Allows access to secret material or secret-backed host APIs. | Keep `false` unless the plugin is explicitly a credential/status integration. |
| `env_read` | env var list | Leaks tokens, account names, paths, cloud profile state. | Exact non-secret variables. Avoid broad credential vars. |
| `pre_exec` | bool | Can inspect or gate commands before execution. High workflow impact. | Only safety plugins; require explicit trust and clear user-facing behavior. |

## Filesystem scopes

- Exact paths match one path.
- Recursive scopes end in `/**`.
- `~/` resolves against the loading user's home directory.
- Relative scopes resolve under the plugin directory.

Examples:

```lua
fs_read = { "~/.kube/config" }
fs_watch = { "~/.config/gcloud/**" }
```

Avoid:

```lua
fs_read = { "~/**" }
exec = { "sh", "bash", "python" }
net = { "*" }
```

## Trust prompts

The daemon loads only plugins recorded in `plugins.trusted`. A capability-free manifest needs an explicit name record; a manifest that requests host access must also match its recorded capability fingerprint. `shisa plugin install` records that approval after an interactive confirmation. `shisa plugin install --yes` installs without granting runtime trust; follow it with `shisa plugin trust <name>` to approve the exact installed manifest. `shisa plugin trust <name> --net=<provider>` records a provider-scoped network grant for a net-only manifest; it does not trust other providers or non-network capabilities. A plugin upgrade that changes requested capabilities must be treated as a new trust decision.

## Review checklist

- Does the plugin work with fewer capabilities?
- Are all path scopes exact or narrow?
- Is any command execution async and bounded?
- Is network access tied to one provider?
- Are env vars non-secret?
- Is `pre_exec` necessary for the user-visible feature?
