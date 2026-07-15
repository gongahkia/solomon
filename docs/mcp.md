# MCP

`stonks-mcp` exposes paper-first stonks-cli capabilities to MCP clients. It never places orders, accepts secrets, arms live trading, or changes legal-policy settings.

## Start

From a source checkout, allow the repository as an MCP file root and start stdio:

```console
$ export STONKS_CLI_MCP_ROOTS="$PWD"
$ uv run stonks-mcp
```

Use Streamable HTTP only for local clients. It binds to loopback and requires a bearer token:

```console
$ export STONKS_CLI_MCP_TOKEN="$(openssl rand -hex 32)"
$ uv run stonks-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

The endpoint is `http://127.0.0.1:8765/mcp`.

`STONKS_CLI_MCP_ROOTS` is path-separated (`:` on macOS/Linux). Tools may use only those roots plus the managed config/state/cache directories. Do not use a broad root such as `$HOME`.

## Mutations

Configuration, artifacts, jobs, clean, and uninstall require `prepare_mutation`, then `confirm_mutation`. Confirmation IDs expire after five minutes and work once. MCP clients must retain their own user approval prompts.

Only these config fields are writable: carry alert settings and APR threshold; local read-only Moomoo enablement/endpoint/account ID; crypto-research enablement/cadence; and operator-report enablement. Paper mode is re-enforced and live execution remains disabled.

## Client configuration

Use absolute checkout paths below.

### Codex

```console
$ codex mcp add stonks --env STONKS_CLI_MCP_ROOTS=/absolute/path/to/stonks-cli -- uv --directory /absolute/path/to/stonks-cli run stonks-mcp
$ codex mcp list
```

For HTTP, start the server separately, then configure `codex mcp add stonks-http --url http://127.0.0.1:8765/mcp --bearer-token-env-var STONKS_CLI_MCP_TOKEN`.

### Claude Code

```console
$ claude mcp add --transport stdio stonks --env STONKS_CLI_MCP_ROOTS=/absolute/path/to/stonks-cli -- uv --directory /absolute/path/to/stonks-cli run stonks-mcp
$ claude mcp get stonks
```

### OpenClaw

```console
$ openclaw mcp add stonks --command uv --arg=--directory --arg=/absolute/path/to/stonks-cli --arg=run --arg=stonks-mcp
$ openclaw mcp doctor stonks --probe
```

Set `STONKS_CLI_MCP_ROOTS` in the saved server environment and restrict the tool filter to the tools needed by that agent.

### Hermes

Add this to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  stonks:
    command: uv
    args: ["--directory", "/absolute/path/to/stonks-cli", "run", "stonks-mcp"]
    env:
      STONKS_CLI_MCP_ROOTS: /absolute/path/to/stonks-cli
    supports_parallel_tool_calls: false
```

Restart Hermes and inspect its discovered `mcp_stonks_*` tools.

## Tool groups

<<<<<<< HEAD
- Read-only: `status`, `doctor`, `config_get`, `config_validate`, `carry_scan`, `carry_health`, `capture_gate_status`, `research_rank_wallets`, `research_replay_paper`, `carry_preflight`, `job_status`, `job_list`.
- `cli_readonly` safely bridges the remaining allowlisted non-mutating CLI commands, including the read-only Moomoo and vNext operations; it does not grant shell access or permit write/live-mode options.
=======
- Read-only: `status`, `doctor`, `config_get`, `config_validate`, `carry_scan`, `research_rank_wallets`, `research_replay_paper`, `carry_preflight`, `job_status`, `job_list`.
>>>>>>> e181ba5e114ca4956b07dab58f74326f08a9bb01
- Confirmation-gated: `prepare_mutation`, `confirm_mutation` for onboarding/settings, fixture artifacts, capture samples, paper jobs, cancellation, cleanup, and uninstall.

All results are structured JSON. Sensitive config values are redacted.
