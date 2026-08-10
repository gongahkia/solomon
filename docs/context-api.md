# Local Context API

`shisa context` exposes a versioned snapshot of values already cached by `shisad`. It is intended for local terminal status bars, editors, and coding CLIs that would otherwise repeat Git or cloud-context reads.

```sh
shisa context --json
shisa context --socket /tmp/shisa.sock --cwd "$PWD" --json
```

The command writes one JSON object to standard output and uses the existing local Unix socket (or Windows named pipe). There is no TCP listener, authentication token, capability grant, filesystem probe, environment read, subprocess, or network request in the `context` operation. On Unix, the socket is owner-only (`0600`); on Windows, the pipe DACL permits only the current logon session.

## Contract

The response has protocol version `v: 2` and schema identifier `shisa.context/v1`:

```json
{
  "v": 2,
  "schema": "shisa.context/v1",
  "request_id": "context-cli",
  "context": {
    "cwd": "/work/service",
    "git": {"state": "ready", "generation": 12, "value": "git:main*"},
    "language": {"state": "pending", "generation": 8, "value": null},
    "cloud": {
      "gcp": {"state": "ready", "generation": 4, "value": "sandbox-project"},
      "azure": {"state": "unknown", "generation": 0, "value": null},
      "kubernetes": {"state": "ready", "generation": 6, "value": "dev/default"}
    },
    "config_generation": 2,
    "plugin_generation": 5
  }
}
```

`value` is always present and is either a cached display value or `null`. `generation` changes when that cache slot is invalidated or replaced; it allows clients to discard their own derived state without polling module files.

`state` has a deliberately small vocabulary:

- `unknown`: the daemon has not populated this cache.
- `pending`: an async value for the requested working directory is being populated.
- `ready`: the cache has completed; `value: null` means the check found no applicable context.
- `stale`: a cwd-scoped cache currently holds another working directory's result, so its value is withheld.

Cloud cache values are process-wide and currently use `unknown` or `ready`. The API reports cached display values only; it does not expose credentials, tokens, command history, environment variables, or plugin capabilities.

## Framed protocol

Clients that need to avoid spawning `shisa` can connect to the same local socket and send one length-prefixed UTF-8 JSON request. The frame is a four-byte big-endian unsigned payload length followed by JSON:

```json
{"v":2,"op":"context","cwd":"/work/service","request_id":"statusline-42"}
```

The daemon returns one frame containing the response object, then closes the connection. Invalid requests receive a regular error envelope with `E_MALFORMED`. The request is read-only by design; use the existing `reload` operation only when a caller is authorized to refresh daemon configuration.

## Client guidance

Treat `pending`, `unknown`, and `stale` as absence rather than failures. Do not invoke a cloud CLI or repository scan to fill them: render a normal prompt or wait for a later snapshot. This keeps a consumer from accidentally defeating the daemon’s latency and no-network defaults.
