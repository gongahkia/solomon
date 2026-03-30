# stonks-cli Value Proposition, Structure, and Upgrade Notes

## 1. Repository Purpose and Intent

`stonks-cli` is a batteries-included terminal-first market analysis toolkit that combines:

- everyday investor workflows (quick signal checks, watchlists, alerts, paper trading), and
- developer workflows (configurable providers, plugin strategy/provider extension points, MCP tools for agent integration).

The repository intent is not just "show stock prices", but to provide a practical local decision-support layer that can be scripted, scheduled, inspected, and embedded.

## 2. Structural Map (What Each Area Is For)

- `src/stonks_cli/cli.py`: Typer CLI entrypoint and command UX.
- `src/stonks_cli/commands.py`: orchestration/service layer shared by CLI and MCP.
- `src/stonks_cli/pipeline.py`: analysis engine (provider selection, indicator prep, strategy execution, risk overlays, backtest metrics).
- `src/stonks_cli/data/*`: provider and market/fundamental/news/dividend integrations + cache.
- `src/stonks_cli/reporting/*`: text/json/csv outputs.
- `src/stonks_cli/scheduler/*`: APScheduler orchestration, pid locking, schedule run behavior.
- `src/stonks_cli/alerts/*`: alert models, persistence, checks, notifications.
- `src/stonks_cli/portfolio/*`: portfolio state, paper trading, history/performance.
- `src/stonks_cli/mcp_server.py`: MCP tool surface for AI-agent integration.
- `tests/*`: behavior-driven regression coverage across commands, providers, scheduler, reporting, plugins.
- `.github/workflows/ci.yml`: lint (`ruff`), typecheck (`mypy`), tests (3 Python versions), and package build.

## 3. Philosophical Value Proposition (Before and After)

### Before this upgrade

The project already had broad feature coverage, but key adoption friction remained:

- Too many workflows required users to manually stitch multiple commands.
- Some exception paths failed quietly, reducing trust during debugging.
- Diagnostics existed, but lacked a direct health score and remediation framing.
- No persistent first-class event ledger for postmortems and operational troubleshooting.

### After this upgrade

The value proposition is now sharper:

- **One-command situational awareness** for normal users via `snapshot`.
- **Explicit observability and forensics** for developers via structured event tracking.
- **Better guardrails and fail-loud behavior** in alert validation and core error paths.
- **Stronger cross-surface parity** by exposing the same snapshot capability in MCP.

## 4. Market Convention Research (What We Anchored Against)

The upgrade direction was calibrated against active FOSS market-tool conventions:

- `achannarasappa/ticker` emphasizes live watchlist UX, positions, summary views, and explicit debug logging output.
  - Source: https://github.com/achannarasappa/ticker
- `tickrs` emphasizes terminal summary mode, chart/timeframe controls, and update interval ergonomics.
  - Source: https://docs.rs/crate/tickrs/latest/source/README.md
- `yfinance` emphasizes broad component surface (single/multi ticker, search, websocket, screener) and transparent legal/provider boundaries.
  - Source: https://github.com/ranaroussi/yfinance
- `OpenBB` emphasizes “connect once, consume everywhere” across Python, CLI, APIs, and MCP/agent surfaces.
  - Source: https://github.com/OpenBB-finance/OpenBB

### Derived conventions applied here

- Provide an immediate summary mode for fast daily use.
- Keep multi-surface capabilities aligned (CLI + MCP).
- Make diagnostics and operational logs explicit and machine-readable.
- Fail clearly when user input is invalid (especially alert conditions).

## 5. Upgrades Implemented

### 5.1 New capability: Market Snapshot

Added `do_market_snapshot` and CLI command `stonks-cli snapshot`.

Snapshot consolidates in one call:

- per-ticker action/confidence/price/change,
- data freshness (`last_data_date`, `data_age_days`, `stale`),
- top movers,
- unusual-volume hits,
- alert counts (`total`, `enabled`, `triggered`),
- signal-diff availability and count,
- user-facing notes for missing/stale baselines.

Also exposed via MCP as `get_market_snapshot` for agent parity.

### 5.2 Reliability and observability hardening

Added persistent event logging primitives in `logging_utils`:

- `track_event(...)` writes to state `events.jsonl` and emits logs.
- `log_suppressed_exception(...)` captures context for previously quiet failures.

Applied to high-impact paths including:

- config normalization fallback,
- state/history/cache parsing failures,
- provider fetch/parse failures,
- scheduler lifecycle and shutdown failure handling,
- alert storage/check/webhook flows,
- portfolio and paper-price concurrent fetch fallbacks,
- data purge fallback branches,
- unusual/dividend/movers per-ticker suppression points.

### 5.3 UX and guardrail improvements

- `doctor` now includes:
  - `health_score`,
  - actionable `next_steps` summary.
- CLI `doctor` now surfaces score prominently.
- `do_alert_add` now validates condition names and raises clear `ValueError` on invalid inputs.
- Webhook notifications now validate HTTP status (`raise_for_status`) and log failure context.
- Removed duplicate dead `return` in paper leaderboard command path.

## 6. Test Coverage Added/Updated

Added:

- `tests/test_market_snapshot.py`
  - validates snapshot shape, stale detection, and core section availability.
- `tests/test_alert_validation.py`
  - validates unknown alert conditions are rejected.
- `tests/test_event_logging.py`
  - validates structured event persistence to `events.jsonl`.

Updated:

- `tests/test_doctor_output_smoke.py`
  - now asserts `health_score` and `next_steps` are present.

## 7. CI/CD and Local Verification Expectation

CI contract in this repo remains:

- Ruff lint + format check
- mypy
- pytest
- build step

Upgrade work was built to preserve that contract and extend tests where new behaviors were introduced.

## 8. Practical Usage Improvements for Adoption

### For everyday users

- Use `stonks-cli snapshot` as daily entrypoint.
- Use `stonks-cli snapshot --json` when piping into other tools.
- Snapshot now warns about stale data and missing diff baselines explicitly.

### For developers

- Use `--structured-logs` + state `events.jsonl` for deterministic issue triage.
- Use MCP `get_market_snapshot` for agentic workflows with the same semantics as CLI.
- Doctor score + guidance now gives immediate environment and configuration direction.

## 9. Forward-Looking Opportunities

If continuing expansion, highest-leverage next steps are:

- provider-level latency/timeout metrics in snapshot and doctor outputs,
- optional notification routing profiles (terminal/webhook/email) with retry policy,
- strategy explainability section in reports (signal factor contributions),
- profile presets for beginner vs advanced output verbosity.
