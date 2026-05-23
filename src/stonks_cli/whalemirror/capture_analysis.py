from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_CAPTURE_TARGET_SECONDS = 7 * 24 * 60 * 60


def analyze_capture_archive(
    *,
    capture_dir: Path | str,
    raw_path: Path | str | None = None,
    normalized_path: Path | str | None = None,
    health_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    target_seconds: float = DEFAULT_CAPTURE_TARGET_SECONDS,
    top_limit: int = 20,
) -> dict[str, Any]:
    """Analyze an archived WhaleMirror capture without changing source files."""
    use_capture_dir = Path(capture_dir)
    use_output_dir = Path(output_dir) if output_dir is not None else use_capture_dir
    use_raw_path = Path(raw_path) if raw_path is not None else use_capture_dir / "hyperliquid-raw.jsonl"
    use_normalized_path = (
        Path(normalized_path) if normalized_path is not None else use_capture_dir / "hyperliquid-normalized.jsonl"
    )
    use_health_path = Path(health_path) if health_path is not None else use_capture_dir / "capture-health.json"

    health = _read_json(use_health_path)
    raw_summary = _summarize_raw(use_raw_path)
    normalized_summary = _summarize_normalized(use_normalized_path, top_limit=top_limit)
    synthesis = _synthesize(
        capture_dir=use_capture_dir,
        raw_path=use_raw_path,
        normalized_path=use_normalized_path,
        health_path=use_health_path,
        health=health,
        raw=raw_summary,
        normalized=normalized_summary,
        target_seconds=target_seconds,
    )

    use_output_dir.mkdir(parents=True, exist_ok=True)
    analysis_json = use_output_dir / "partial-capture-analysis.json"
    analysis_md = use_output_dir / "partial-capture-analysis.md"
    executive_summary = use_output_dir / "executive-summary.md"
    analysis_json.write_text(json.dumps(synthesis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    analysis_md.write_text(_render_analysis_markdown(synthesis), encoding="utf-8")
    executive_summary.write_text(_render_executive_summary(synthesis), encoding="utf-8")

    return {
        "analysis_json_path": str(analysis_json),
        "analysis_report_path": str(analysis_md),
        "executive_summary_path": str(executive_summary),
        "summary": synthesis,
    }


def _summarize_raw(path: Path) -> dict[str, Any]:
    channels: Counter[str] = Counter()
    first_received: str | None = None
    last_received: str | None = None
    line_count = 0
    parse_errors = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            line_count += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            received = row.get("received_at_utc")
            if isinstance(received, str) and received:
                first_received = received if first_received is None else min(first_received, received)
                last_received = received if last_received is None else max(last_received, received)
            payload = row.get("raw") if isinstance(row.get("raw"), dict) else {}
            channels[str(payload.get("channel") or "unknown")] += 1

    return {
        "path": str(path),
        "line_count": line_count,
        "parse_errors": parse_errors,
        "first_received_at_utc": first_received,
        "last_received_at_utc": last_received,
        "channels": dict(channels),
    }


def _summarize_normalized(path: Path, *, top_limit: int) -> dict[str, Any]:
    line_count = 0
    parse_errors = 0
    markets: Counter[str] = Counter()
    sides: Counter[str] = Counter()
    wallet_rows: Counter[str] = Counter()
    wallet_notional: Counter[str] = Counter()
    market_unique_events: Counter[str] = Counter()
    market_unique_notional: Counter[str] = Counter()
    utc_days: Counter[str] = Counter()
    unique_wallets: set[str] = set()
    unique_events: set[str] = set()
    first_observed: str | None = None
    last_observed: str | None = None
    largest_rows: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            line_count += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            market = str(row.get("market") or "unknown")
            side = str(row.get("side") or "unknown")
            wallet = str(row.get("wallet") or "unknown").lower()
            notional = float(row.get("notional_usd") or 0.0)
            observed = str(row.get("observed_at") or "")
            trade_id = str(row.get("trade_id") or "")
            event_id = trade_id.rsplit(":", 1)[0] if ":" in trade_id else trade_id

            markets[market] += 1
            sides[side] += 1
            wallet_rows[wallet] += 1
            wallet_notional[wallet] += notional
            unique_wallets.add(wallet)
            if event_id and event_id not in unique_events:
                unique_events.add(event_id)
                market_unique_events[market] += 1
                market_unique_notional[market] += notional

            if observed:
                first_observed = observed if first_observed is None else min(first_observed, observed)
                last_observed = observed if last_observed is None else max(last_observed, observed)
                parsed = _parse_ts_or_none(observed)
                if parsed is not None:
                    utc_days[parsed.date().isoformat()] += 1

            if notional > 0:
                _keep_largest(
                    largest_rows,
                    {
                        "notional_usd": round(notional, 4),
                        "observed_at": observed,
                        "market": market,
                        "side": side,
                        "wallet": wallet,
                        "trade_id": trade_id,
                    },
                    limit=top_limit,
                )

    largest_rows.sort(key=lambda row: float(row["notional_usd"]), reverse=True)
    return {
        "path": str(path),
        "line_count": line_count,
        "parse_errors": parse_errors,
        "unique_wallets": len(unique_wallets),
        "unique_trade_events": len(unique_events),
        "first_observed_at_utc": first_observed,
        "last_observed_at_utc": last_observed,
        "side_counts": dict(sides),
        "counts_by_utc_day": dict(sorted(utc_days.items())),
        "top_markets_by_rows": _top(markets, top_limit),
        "top_markets_by_unique_events": _top(market_unique_events, top_limit),
        "top_markets_by_unique_event_notional_usd": _top_float(market_unique_notional, top_limit),
        "top_wallets_by_rows": _top(wallet_rows, top_limit),
        "top_wallets_by_row_notional_usd": _top_float(wallet_notional, top_limit),
        "largest_normalized_rows": largest_rows,
    }


def _synthesize(
    *,
    capture_dir: Path,
    raw_path: Path,
    normalized_path: Path,
    health_path: Path,
    health: dict[str, Any],
    raw: dict[str, Any],
    normalized: dict[str, Any],
    target_seconds: float,
) -> dict[str, Any]:
    health_payload = health.get("health") if isinstance(health.get("health"), dict) else {}
    duration_seconds = float(health.get("duration_seconds") or _observed_duration_seconds(normalized) or 0.0)
    factor = target_seconds / duration_seconds if duration_seconds > 0 else 0.0
    projected_rows = int(round(int(normalized["line_count"]) * factor)) if factor else 0
    projected_events = int(round(int(normalized["unique_trade_events"]) * factor)) if factor else 0

    return {
        "created_at_utc": _iso(_now()),
        "capture_dir": str(capture_dir),
        "source_paths": {
            "raw": str(raw_path),
            "normalized": str(normalized_path),
            "health": str(health_path),
        },
        "health": {
            "started_at_utc": health.get("started_at_utc"),
            "updated_at_utc": health.get("updated_at_utc"),
            "duration_seconds_reported": health.get("duration_seconds"),
            "duration_hours_reported": round(duration_seconds / 3600, 4) if duration_seconds else 0.0,
            "final_status": health.get("final_status"),
            "last_error": health_payload.get("last_error"),
            "messages_received": health_payload.get("messages_received"),
            "decoded_events": health_payload.get("decoded_events"),
            "decoded_trades": health_payload.get("decoded_trades"),
            "malformed_messages": health_payload.get("malformed_messages"),
            "dropped_messages": health_payload.get("dropped_messages"),
            "reconnects": health_payload.get("reconnects"),
            "runtime": health.get("runtime"),
        },
        "raw": raw,
        "normalized": normalized,
        "projection": {
            "target_seconds": target_seconds,
            "target_hours": round(target_seconds / 3600, 4),
            "coverage_fraction": round(duration_seconds / target_seconds, 6) if target_seconds > 0 else 0.0,
            "extrapolation_factor": round(factor, 6),
            "projected_target_normalized_rows": projected_rows,
            "projected_missing_normalized_rows": max(0, projected_rows - int(normalized["line_count"])),
            "projected_target_unique_trade_events": projected_events,
            "projected_missing_unique_trade_events": max(0, projected_events - int(normalized["unique_trade_events"])),
        },
        "interpretation": {
            "gate_status": "partial_only_not_7_day_pass",
            "normalized_rows_double_count_public_trades": True,
            "wallet_rankings_are_activity_not_profitability": True,
            "synthetic_projection_is_planning_only": True,
        },
    }


def _render_analysis_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# WhaleMirror Partial Capture Analysis",
        "",
        "## Gate Context",
        "",
        "- Related GitHub issue: #13, 7-day Hyperliquid connector clean capture.",
        "- This archive is useful partial live evidence, but it does not satisfy #13.",
        "- Normalized rows represent both sides of public trades.",
        "",
        "## Capture Health",
        "",
    ]
    health = summary["health"]
    for label, key in [
        ("Started", "started_at_utc"),
        ("Last health update", "updated_at_utc"),
        ("Reported duration hours", "duration_hours_reported"),
        ("Final status", "final_status"),
        ("Last error", "last_error"),
        ("Reconnects", "reconnects"),
        ("Malformed messages", "malformed_messages"),
        ("Dropped messages", "dropped_messages"),
    ]:
        lines.append(f"- {label}: `{health.get(key)}`")

    normalized = summary["normalized"]
    raw = summary["raw"]
    lines.extend(
        [
            "",
            "## File Summary",
            "",
            f"- Raw JSONL lines: `{int(raw['line_count']):,}`",
            f"- Normalized JSONL rows: `{int(normalized['line_count']):,}`",
            f"- Unique trade events: `{int(normalized['unique_trade_events']):,}`",
            f"- Unique wallets observed: `{int(normalized['unique_wallets']):,}`",
            f"- First normalized observed timestamp: `{normalized['first_observed_at_utc']}`",
            f"- Last normalized observed timestamp: `{normalized['last_observed_at_utc']}`",
            "",
            "## Top Markets",
            "",
            "| Market | Normalized rows | Unique events | Unique-event notional USD |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    rows_by_market = {row["key"]: row["value"] for row in normalized["top_markets_by_rows"]}
    events_by_market = {row["key"]: row["value"] for row in normalized["top_markets_by_unique_events"]}
    notional_by_market = {row["key"]: row["value"] for row in normalized["top_markets_by_unique_event_notional_usd"]}
    for market, rows in rows_by_market.items():
        lines.append(
            f"| `{market}` | {int(rows):,} | {int(events_by_market.get(market, 0)):,} | "
            f"{float(notional_by_market.get(market, 0.0)):,.2f} |"
        )

    lines.extend(
        [
            "",
            "## Top Wallets By Activity",
            "",
            "| Rank | Wallet | Rows | Row notional USD |",
            "| ---: | --- | ---: | ---: |",
        ]
    )
    wallet_notional = {row["key"]: row["value"] for row in normalized["top_wallets_by_row_notional_usd"]}
    for idx, row in enumerate(normalized["top_wallets_by_rows"], start=1):
        wallet = row["key"]
        lines.append(f"| {idx} | `{wallet}` | {int(row['value']):,} | {float(wallet_notional.get(wallet, 0.0)):,.2f} |")

    projection = summary["projection"]
    lines.extend(
        [
            "",
            "## Synthetic Projection",
            "",
            f"- Target hours: `{projection['target_hours']}`",
            f"- Coverage fraction: `{projection['coverage_fraction']:.2%}`",
            f"- Projected target normalized rows: `{int(projection['projected_target_normalized_rows']):,}`",
            f"- Projected missing normalized rows: `{int(projection['projected_missing_normalized_rows']):,}`",
            "",
            "Synthetic projection is for planning only and is not validation evidence.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_executive_summary(summary: dict[str, Any]) -> str:
    health = summary["health"]
    normalized = summary["normalized"]
    projection = summary["projection"]
    lines = [
        "# WhaleMirror Partial Capture Executive Summary",
        "",
        "## Main Takeaway",
        "",
        "The partial live capture is useful enough to continue exploratory WhaleMirror analysis, but it does not satisfy the formal 7-day clean-capture validation gate.",
        "",
        "The connector decoded a large live Hyperliquid sample without malformed or dropped messages. The run stopped early, so it cannot be used as uninterrupted production-readiness evidence.",
        "",
        "## What We Learned",
        "",
        f"- Real capture window: about {health['duration_hours_reported']} hours.",
        f"- Real normalized rows: {int(normalized['line_count']):,}.",
        f"- Real unique trade events: {int(normalized['unique_trade_events']):,}.",
        f"- Real unique wallets observed: {int(normalized['unique_wallets']):,}.",
        f"- Capture health: {health['malformed_messages']} malformed messages and {health['dropped_messages']} dropped messages.",
        f"- Reconnects: {health['reconnects']}.",
        f"- Last recorded error: `{health['last_error']}`.",
        "",
        "## What This Supports",
        "",
        "- Connector quality analysis.",
        "- Activity-based wallet screening.",
        "- Sizing assumptions for future capture volume.",
        "- Selecting candidate wallets for deeper public-source checks.",
        "",
        "## What This Does Not Support",
        "",
        "- Closing GitHub issue #13.",
        "- Claiming a completed 7-day clean capture.",
        "- Claiming wallet alpha or profitability.",
        "- Ranking wallets as mirror targets without closed-position outcomes, fees, funding, leverage, and public-source sanity checks.",
        "",
        "## Synthetic Projection",
        "",
        f"- Projected target normalized rows: {int(projection['projected_target_normalized_rows']):,}.",
        f"- Projected missing normalized rows: {int(projection['projected_missing_normalized_rows']):,}.",
        "",
        "Synthetic projection is planning-only and must not be treated as validation evidence.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _top(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    return [{"key": key, "value": value} for key, value in counter.most_common(limit)]


def _top_float(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    return [{"key": key, "value": round(value, 4)} for key, value in counter.most_common(limit)]


def _keep_largest(rows: list[dict[str, Any]], row: dict[str, Any], *, limit: int) -> None:
    if len(rows) < limit:
        rows.append(row)
        rows.sort(key=lambda item: float(item["notional_usd"]))
        return
    if float(row["notional_usd"]) > float(rows[0]["notional_usd"]):
        rows[0] = row
        rows.sort(key=lambda item: float(item["notional_usd"]))


def _observed_duration_seconds(summary: dict[str, Any]) -> float | None:
    first = _parse_ts_or_none(str(summary.get("first_observed_at_utc") or ""))
    last = _parse_ts_or_none(str(summary.get("last_observed_at_utc") or ""))
    if first is None or last is None:
        return None
    return max(0.0, (last - first).total_seconds())


def _parse_ts_or_none(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
