from __future__ import annotations

import json
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

DEFAULT_REPLAY_FIXTURE = Path("tests/fixtures/whalemirror/paper-decisions.jsonl")
DEFAULT_LEDGER_PATH = Path("docs/decision-ledger.md")
DEFAULT_TEARSHEET_PATH = Path("docs/whalemirror-fixture-tearsheet.md")


@dataclass(frozen=True)
class ReplayTrace:
    observed_trade: dict[str, Any]
    execution_intent: dict[str, Any]
    decision: dict[str, Any]
    outcome: dict[str, Any]

    @property
    def realized_pnl_usd(self) -> float:
        return _as_float(self.outcome.get("realized_pnl_usd"))

    @property
    def return_pct(self) -> float:
        return _as_float(self.outcome.get("return_pct"))

    @property
    def status(self) -> str:
        return str(self.outcome.get("status") or self.decision.get("outcome") or "unknown")


def load_replay_fixture(path: Path | str = DEFAULT_REPLAY_FIXTURE) -> list[ReplayTrace]:
    use_path = Path(path)
    traces: list[ReplayTrace] = []
    for line_no, line in enumerate(use_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{use_path}:{line_no}: invalid json") from e
        traces.append(_parse_trace(row, source=f"{use_path}:{line_no}"))
    return traces


def build_tearsheet(traces: list[ReplayTrace]) -> dict[str, float | int]:
    pnls = [trace.realized_pnl_usd for trace in traces]
    returns = [trace.return_pct for trace in traces]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "decisions": len(traces),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(traces), 4) if traces else 0.0,
        "realized_pnl_usd": round(sum(pnls), 6),
        "expectancy_usd": round(sum(pnls) / len(traces), 6) if traces else 0.0,
        "avg_win_usd": round(gross_win / len(wins), 6) if wins else 0.0,
        "avg_loss_usd": round(-gross_loss / len(losses), 6) if losses else 0.0,
        "sharpe": _sharpe(returns),
        "avg_decay_hours": round(_avg(_as_float(trace.outcome.get("decay_hours")) for trace in traces), 6),
        "survivorship_adjusted_pnl_usd": round(
            sum(
                _as_float(
                    trace.outcome.get("survivorship_adjusted_pnl_usd"),
                    default=trace.realized_pnl_usd,
                )
                for trace in traces
            ),
            6,
        ),
        "funding_adjusted_pnl_usd": round(
            sum(
                _as_float(
                    trace.outcome.get("funding_adjusted_pnl_usd"),
                    default=trace.realized_pnl_usd + _as_float(trace.outcome.get("funding_usd")),
                )
                for trace in traces
            ),
            6,
        ),
        "gross_win_usd": round(gross_win, 6),
        "gross_loss_usd": round(-gross_loss, 6),
    }


def render_decision_ledger(traces: list[ReplayTrace]) -> str:
    metrics = build_tearsheet(traces)
    lines = [
        "# Decision Ledger",
        "",
        "This is the repository-backed public ledger selected in `docs/product-decisions.md`.",
        "",
        "The ledger is markdown-first for Phase 1. It can be generated or mirrored into a static site later, but repo history remains the source of truth.",
        "",
        "## Fixture Replay Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Decisions | {metrics['decisions']} |",
        f"| Wins | {metrics['wins']} |",
        f"| Losses | {metrics['losses']} |",
        f"| Realized PnL USD | {_money(metrics['realized_pnl_usd'])} |",
        f"| Expectancy USD | {_money(metrics['expectancy_usd'])} |",
        f"| Sharpe | {metrics['sharpe']:.4f} |",
        f"| Average decay hours | {metrics['avg_decay_hours']:.2f} |",
        f"| Survivorship-adjusted PnL USD | {_money(metrics['survivorship_adjusted_pnl_usd'])} |",
        f"| Funding-adjusted PnL USD | {_money(metrics['funding_adjusted_pnl_usd'])} |",
        "",
        "## Decisions",
        "",
        "| Timestamp UTC | Observed Trade | Wallet | Market | Mode | Decision | Rationale | Receipt | Outcome | Realized PnL |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for trace in traces:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(trace.decision.get("timestamp_utc")),
                    _cell(_observed_trade_label(trace.observed_trade)),
                    _cell(trace.observed_trade.get("wallet")),
                    _cell(trace.observed_trade.get("market")),
                    _cell(trace.decision.get("mode")),
                    _cell(trace.decision.get("decision")),
                    _cell(trace.decision.get("rationale")),
                    _cell(trace.decision.get("receipt")),
                    _cell(trace.status),
                    _money(trace.realized_pnl_usd),
                ]
            )
            + " |"
        )
    lines.extend(_ledger_rules())
    return "\n".join(lines) + "\n"


def render_tearsheet(traces: list[ReplayTrace]) -> str:
    metrics = build_tearsheet(traces)
    lines = [
        "# WhaleMirror Fixture Tearsheet",
        "",
        "This generated artifact is backed by `tests/fixtures/whalemirror/paper-decisions.jsonl` and is safe to publish before live data exists.",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Decisions | {metrics['decisions']} |",
        f"| Win rate | {metrics['win_rate']:.2%} |",
        f"| Expectancy USD | {_money(metrics['expectancy_usd'])} |",
        f"| Sharpe | {metrics['sharpe']:.4f} |",
        f"| Average decay hours | {metrics['avg_decay_hours']:.2f} |",
        f"| Survivorship-adjusted PnL USD | {_money(metrics['survivorship_adjusted_pnl_usd'])} |",
        f"| Funding-adjusted PnL USD | {_money(metrics['funding_adjusted_pnl_usd'])} |",
        "",
        "## Win/Loss Visibility",
        "",
        "| Bucket | Count | Gross PnL | Average PnL |",
        "| --- | ---: | ---: | ---: |",
        f"| Wins | {metrics['wins']} | {_money(metrics['gross_win_usd'])} | {_money(metrics['avg_win_usd'])} |",
        f"| Losses | {metrics['losses']} | {_money(metrics['gross_loss_usd'])} | {_money(metrics['avg_loss_usd'])} |",
        "",
        "## Replay Trace",
        "",
        "| Trade ID | Paper receipt | Status | Return | Fees | Funding | Slippage bps |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for trace in traces:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(trace.observed_trade.get("trade_id")),
                    _cell(trace.decision.get("receipt")),
                    _cell(trace.status),
                    f"{trace.return_pct:.2%}",
                    _money(_as_float(trace.outcome.get("fees_usd"))),
                    _money(_as_float(trace.outcome.get("funding_usd"))),
                    f"{_as_float(trace.outcome.get('slippage_bps')):.2f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_fixture_artifacts(
    *,
    fixture_path: Path | str = DEFAULT_REPLAY_FIXTURE,
    ledger_path: Path | str = DEFAULT_LEDGER_PATH,
    tearsheet_path: Path | str = DEFAULT_TEARSHEET_PATH,
) -> dict[str, Any]:
    traces = load_replay_fixture(fixture_path)
    ledger = Path(ledger_path)
    tearsheet = Path(tearsheet_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    tearsheet.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(render_decision_ledger(traces), encoding="utf-8")
    tearsheet.write_text(render_tearsheet(traces), encoding="utf-8")
    return {
        "fixture_path": str(fixture_path),
        "ledger_path": str(ledger),
        "tearsheet_path": str(tearsheet),
        **build_tearsheet(traces),
    }


def _parse_trace(row: dict[str, Any], *, source: str) -> ReplayTrace:
    required = ("observed_trade", "execution_intent", "decision", "outcome")
    missing = [key for key in required if not isinstance(row.get(key), dict)]
    if missing:
        raise ValueError(f"{source}: missing trace sections: {', '.join(missing)}")
    return ReplayTrace(
        observed_trade=dict(row["observed_trade"]),
        execution_intent=dict(row["execution_intent"]),
        decision=dict(row["decision"]),
        outcome=dict(row["outcome"]),
    )


def _ledger_rules() -> list[str]:
    return [
        "",
        "## Ledger Rules",
        "",
        "- Record paper and live decisions with equal prominence.",
        "- Record losses with the same visibility as wins.",
        "- Include enough context to replay the decision from fixtures, logs, or venue receipts.",
        "- Prefer expectancy, Sharpe, decay, survivorship-adjusted PnL, funding, and slippage over unsupported alpha language.",
        "- Do not include Polymarket, Kalshi, sportsbook, or circumvention-based execution from Singapore.",
    ]


def _observed_trade_label(trade: dict[str, Any]) -> str:
    return (
        f"{trade.get('trade_id')} "
        f"{trade.get('side')} "
        f"{trade.get('size')} {trade.get('asset')} "
        f"@ {trade.get('price')}"
    )


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    std = sqrt(variance)
    return round(mean / std, 4) if std > 1e-12 else 0.0


def _avg(values: Any) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def _as_float(value: Any, *, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any) -> str:
    number = _as_float(value)
    if number < 0:
        return f"-${abs(number):.2f}"
    return f"${number:.2f}"


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "/")
