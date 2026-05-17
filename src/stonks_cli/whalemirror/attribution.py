from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any

from stonks_cli.whalemirror.models import AttributionMetrics, TradeSide, Venue, coerce_side

DEFAULT_ATTRIBUTION_FIXTURE = Path("tests/fixtures/whalemirror/wallet-attribution.jsonl")


@dataclass(frozen=True)
class WalletTradeOutcome:
    wallet: str
    venue: Venue
    market: str
    asset: str
    trade_id: str
    side: TradeSide
    entry_px: float
    exit_px: float
    size: float
    opened_at: str
    closed_at: str
    fee_usd: float = 0.0
    leverage: float = 1.0

    @property
    def notional_usd(self) -> float:
        return self.entry_px * self.size

    @property
    def gross_pnl_usd(self) -> float:
        direction = 1.0 if self.side in {TradeSide.BUY, TradeSide.LONG} else -1.0
        return (self.exit_px - self.entry_px) * self.size * direction

    @property
    def net_pnl_usd(self) -> float:
        return self.gross_pnl_usd + self.fee_usd

    @property
    def return_pct(self) -> float:
        return self.net_pnl_usd / self.notional_usd if self.notional_usd > 0 else 0.0


@dataclass(frozen=True)
class FundingEvent:
    wallet: str
    venue: Venue
    market: str
    asset: str
    timestamp_utc: str
    funding_usd: float
    funding_rate: float = 0.0


@dataclass(frozen=True)
class WalletRanking:
    metrics: AttributionMetrics
    expectancy_pct: float
    realized_pnl_usd: float
    leverage_adjusted_pnl_usd: float
    rolling_sharpe: list[float]
    max_leverage: float
    win_rate: float
    gross_funding_usd: float

    def to_dict(self) -> dict[str, Any]:
        payload = self.metrics.to_dict()
        payload.update(
            {
                "expectancy_pct": self.expectancy_pct,
                "realized_pnl_usd": self.realized_pnl_usd,
                "leverage_adjusted_pnl_usd": self.leverage_adjusted_pnl_usd,
                "rolling_sharpe": self.rolling_sharpe,
                "max_leverage": self.max_leverage,
                "win_rate": self.win_rate,
                "gross_funding_usd": self.gross_funding_usd,
            }
        )
        return payload


def load_attribution_fixture(
    path: Path | str = DEFAULT_ATTRIBUTION_FIXTURE,
) -> tuple[list[WalletTradeOutcome], list[FundingEvent]]:
    trades: list[WalletTradeOutcome] = []
    fundings: list[FundingEvent] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{line_no}: invalid json") from e
        row_type = row.get("type")
        if row_type == "trade_outcome":
            trades.append(_parse_trade_outcome(row))
        elif row_type == "funding":
            fundings.append(_parse_funding(row))
        else:
            raise ValueError(f"{path}:{line_no}: unsupported attribution row type: {row_type!r}")
    return trades, fundings


def rank_wallets(
    trades: list[WalletTradeOutcome],
    fundings: list[FundingEvent] | None = None,
    *,
    min_survivorship_sample: int = 5,
    rolling_window: int = 2,
    limit: int = 100,
) -> list[WalletRanking]:
    funding_by_wallet: dict[str, float] = defaultdict(float)
    for event in fundings or []:
        funding_by_wallet[event.wallet.lower()] += event.funding_usd

    grouped: dict[str, list[WalletTradeOutcome]] = defaultdict(list)
    for trade in trades:
        grouped[trade.wallet.lower()].append(trade)

    rankings = [
        _rank_one_wallet(
            wallet=wallet,
            trades=rows,
            funding_usd=funding_by_wallet.get(wallet, 0.0),
            min_survivorship_sample=min_survivorship_sample,
            rolling_window=rolling_window,
        )
        for wallet, rows in grouped.items()
    ]
    rankings.sort(
        key=lambda row: (
            row.metrics.survivorship_adjusted_pnl,
            row.metrics.funding_adjusted_pnl,
            row.metrics.sample_size,
        ),
        reverse=True,
    )
    return rankings[:limit]


def rank_wallets_from_fixture(path: Path | str = DEFAULT_ATTRIBUTION_FIXTURE, *, limit: int = 100) -> list[WalletRanking]:
    trades, fundings = load_attribution_fixture(path)
    return rank_wallets(trades, fundings, limit=limit)


def render_wallet_ranking_markdown(rankings: list[WalletRanking]) -> str:
    lines = [
        "# WhaleMirror Wallet Ranking",
        "",
        "Fixture ranking uses reproducible trade outcomes and funding events. It is not an alpha claim, and public top-10 validation remains tracked in #15.",
        "",
        "| Rank | Wallet | Expectancy USD | Expectancy % | Sharpe | Decay | Funding-adjusted PnL | Survivorship-adjusted PnL | Sample | Caveats |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, ranking in enumerate(rankings, start=1):
        metrics = ranking.metrics
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    metrics.wallet,
                    f"{metrics.expectancy:.4f}",
                    f"{ranking.expectancy_pct:.4%}",
                    f"{metrics.sharpe:.4f}",
                    f"{metrics.decay:.4f}",
                    f"{metrics.funding_adjusted_pnl:.4f}",
                    f"{metrics.survivorship_adjusted_pnl:.4f}",
                    str(metrics.sample_size),
                    ", ".join(metrics.caveats),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _rank_one_wallet(
    *,
    wallet: str,
    trades: list[WalletTradeOutcome],
    funding_usd: float,
    min_survivorship_sample: int,
    rolling_window: int,
) -> WalletRanking:
    ordered = sorted(trades, key=lambda trade: _parse_ts(trade.closed_at))
    pnls = [trade.net_pnl_usd for trade in ordered]
    returns = [trade.return_pct for trade in ordered]
    sample_size = len(ordered)
    realized_pnl = sum(pnls)
    funding_adjusted_pnl = realized_pnl + funding_usd
    expectancy = funding_adjusted_pnl / sample_size if sample_size else 0.0
    expectancy_pct = sum(returns) / sample_size if sample_size else 0.0
    rolling = _rolling_sharpe(returns, rolling_window)
    decay = (rolling[-1] - rolling[0]) if len(rolling) >= 2 else 0.0
    max_leverage = max((trade.leverage for trade in ordered), default=1.0)
    leverage_adjusted_pnl = sum(trade.net_pnl_usd / max(trade.leverage, 1.0) for trade in ordered)
    survivorship_factor = min(1.0, sample_size / max(min_survivorship_sample, 1))
    survivorship_adjusted_pnl = funding_adjusted_pnl * survivorship_factor
    caveats = _caveats(
        sample_size=sample_size,
        min_survivorship_sample=min_survivorship_sample,
        funding_usd=funding_usd,
        max_leverage=max_leverage,
    )
    wins = sum(1 for pnl in pnls if pnl > 0)
    venue = ordered[0].venue if ordered else Venue.HYPERLIQUID
    metrics = AttributionMetrics(
        wallet=wallet,
        venue=venue,
        expectancy=round(expectancy, 6),
        sharpe=_sharpe(returns),
        decay=round(decay, 6),
        survivorship_adjusted_pnl=round(survivorship_adjusted_pnl, 6),
        funding_adjusted_pnl=round(funding_adjusted_pnl, 6),
        sample_size=sample_size,
        caveats=caveats,
    )
    return WalletRanking(
        metrics=metrics,
        expectancy_pct=round(expectancy_pct, 8),
        realized_pnl_usd=round(realized_pnl, 6),
        leverage_adjusted_pnl_usd=round(leverage_adjusted_pnl, 6),
        rolling_sharpe=rolling,
        max_leverage=round(max_leverage, 4),
        win_rate=round(wins / sample_size, 6) if sample_size else 0.0,
        gross_funding_usd=round(funding_usd, 6),
    )


def _parse_trade_outcome(row: dict[str, Any]) -> WalletTradeOutcome:
    return WalletTradeOutcome(
        wallet=str(row["wallet"]).lower(),
        venue=Venue(str(row.get("venue") or Venue.HYPERLIQUID)),
        market=str(row["market"]),
        asset=str(row["asset"]),
        trade_id=str(row["trade_id"]),
        side=coerce_side(str(row["side"])),
        entry_px=float(row["entry_px"]),
        exit_px=float(row["exit_px"]),
        size=float(row["size"]),
        opened_at=str(row["opened_at"]),
        closed_at=str(row["closed_at"]),
        fee_usd=float(row.get("fee_usd") or 0.0),
        leverage=float(row.get("leverage") or 1.0),
    )


def _parse_funding(row: dict[str, Any]) -> FundingEvent:
    return FundingEvent(
        wallet=str(row["wallet"]).lower(),
        venue=Venue(str(row.get("venue") or Venue.HYPERLIQUID)),
        market=str(row["market"]),
        asset=str(row["asset"]),
        timestamp_utc=str(row["timestamp_utc"]),
        funding_usd=float(row["funding_usd"]),
        funding_rate=float(row.get("funding_rate") or 0.0),
    )


def _caveats(*, sample_size: int, min_survivorship_sample: int, funding_usd: float, max_leverage: float) -> list[str]:
    caveats = ["manual_top_10_validation_pending:#15", "fixture_replay_dataset"]
    if sample_size < min_survivorship_sample:
        caveats.append(f"small_sample:{sample_size}<{min_survivorship_sample}")
    if funding_usd:
        caveats.append("funding_costs_included")
    if max_leverage > 5:
        caveats.append(f"high_leverage:{max_leverage:g}x")
    return caveats


def _rolling_sharpe(returns: list[float], window: int) -> list[float]:
    if window <= 0:
        return []
    return [_sharpe(returns[i : i + window]) for i in range(0, max(len(returns) - window + 1, 0))]


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    std = sqrt(variance)
    return round(mean / std, 6) if std > 1e-12 else 0.0


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
