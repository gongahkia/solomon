# History Interoperability

Shisa does not capture, store, search, repair, or synchronize shell history. History systems such as Atuin remain the owner of those concerns. Shisa supplies only a local context snapshot that another tool can associate with its own history record.

The stable input for that association is [`shisa.context/v1`](context-api.md). A history tool may store an observation alongside its existing command metadata:

```json
{
  "schema": "shisa.history-context/v1",
  "observed_at_unix": 1775430123,
  "command": "kubectl get pods",
  "exit": 0,
  "shisa_context": {
    "schema": "shisa.context/v1",
    "cwd": "/work/service",
    "git": {"state": "ready", "generation": 12, "value": "git:main*"},
    "cloud": {
      "kubernetes": {"state": "ready", "generation": 6, "value": "dev/default"}
    }
  }
}
```

This is a documentation contract, not a Shisa history format or a runtime integration. Shisa does not emit the outer record, read a history database, or transmit it anywhere. An integration owns its command redaction, retention, encryption, synchronization, and database repair policy.

For a lightweight local workflow, query context only at the boundary your history tool already controls:

```sh
context="$(shisa context --json)" || exit 0
# Pass "$context" to your own local history hook after applying its redaction policy.
```

Consumers should record the `schema` value, preserve unknown fields, and treat a non-`ready` entry as unavailable context. Do not infer credentials, account ownership, or a command’s authorization from prompt context.
