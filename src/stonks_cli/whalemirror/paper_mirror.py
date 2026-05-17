from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from stonks_cli.whalemirror.attribution import WalletRanking
from stonks_cli.whalemirror.models import (
    DecisionRecord,
    ExecutionIntent,
    MirrorMode,
    NormalizedTrade,
    TradeSide,
    Venue,
)

DEFAULT_PAPER_MIRROR_FIXTURE = Path("tests/fixtures/whalemirror/paper-mirror.jsonl")


@dataclass(frozen=True)
class PaperMirrorConfig:
    follower_bankroll_usd: float = 1000.0
    max_position_fraction: float = 0.10
    max_order_notional_usd: float = 75.0
    stop_loss_pct: float = 0.08
    cooldown_minutes: float = 60.0
    source_notional_fraction: float = 1.0

    @property
    def bankroll_position_cap_usd(self) -> float:
        return self.follower_bankroll_usd * self.max_position_fraction


@dataclass(frozen=True)
class PaperPosition:
    wallet: str
    market: str
    asset: str
    side: TradeSide
    entry_px: float
    size: float
    notional_usd: float
    opened_at: str
    source_trade_id: str


@dataclass(frozen=True)
class PaperClosedTrade:
    wallet: str
    market: str
    source_trade_id: str
    opened_at: str
    closed_at: str
    entry_px: float
    exit_px: float
    size: float
    realized_pnl_usd: float
    reason: str


@dataclass
class PaperMirrorState:
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    cooldown_until: dict[str, str] = field(default_factory=dict)
    closed_trades: list[PaperClosedTrade] = field(default_factory=list)


@dataclass(frozen=True)
class PaperMirrorDecision:
    intent: ExecutionIntent | None
    ledger_record: DecisionRecord


@dataclass(frozen=True)
class PaperMirrorReplay:
    decisions: list[PaperMirrorDecision]
    tearsheet: dict[str, Any]
    state: PaperMirrorState


class PaperMirrorEngine:
    def __init__(
        self,
        *,
        rankings: list[WalletRanking],
        config: PaperMirrorConfig | None = None,
        state: PaperMirrorState | None = None,
    ) -> None:
        self.rankings = {ranking.metrics.wallet.lower(): ranking for ranking in rankings}
        self.config = config or PaperMirrorConfig()
        self.state = state or PaperMirrorState()

    def process_trade(self, trade: NormalizedTrade) -> PaperMirrorDecision:
        wallet = trade.wallet.lower()
        key = _position_key(wallet, trade.market)
        now = _parse_ts(trade.observed_at)
        cooldown_until = self.state.cooldown_until.get(key)
        if cooldown_until and now < _parse_ts(cooldown_until):
            return PaperMirrorDecision(
                intent=None,
                ledger_record=self._record_skip(
                    trade,
                    decision="skip_cooldown",
                    rationale=f"re-entry cooldown active until {cooldown_until}",
                    metadata={"risk_control": "cooldown", "cooldown_until": cooldown_until},
                ),
            )

        ranking = self.rankings.get(wallet)
        if ranking is None:
            return PaperMirrorDecision(
                intent=None,
                ledger_record=self._record_skip(
                    trade,
                    decision="skip_unranked_wallet",
                    rationale="wallet is not in the selected ranking set",
                    metadata={"risk_control": "wallet_filter"},
                ),
            )

        target_notional = trade.notional_usd * self.config.source_notional_fraction
        cap = min(target_notional, self.config.bankroll_position_cap_usd, self.config.max_order_notional_usd)
        if cap <= 0 or trade.price <= 0:
            return PaperMirrorDecision(
                intent=None,
                ledger_record=self._record_skip(
                    trade,
                    decision="skip_risk_cap",
                    rationale="risk caps produced a zero-sized paper order",
                    metadata={"risk_control": "risk_cap", "target_notional_usd": target_notional},
                ),
            )

        size = cap / trade.price
        size_down_ratio = cap / target_notional if target_notional > 0 else 0.0
        metadata = {
            "ranking_sample_size": ranking.metrics.sample_size,
            "ranking_caveats": ranking.metrics.caveats,
            "target_notional_usd": round(target_notional, 6),
            "bankroll_position_cap_usd": round(self.config.bankroll_position_cap_usd, 6),
            "max_order_notional_usd": round(self.config.max_order_notional_usd, 6),
            "mirror_notional_usd": round(cap, 6),
            "size_down_ratio": round(size_down_ratio, 8),
            "stop_loss_pct": self.config.stop_loss_pct,
            "cooldown_minutes": self.config.cooldown_minutes,
        }
        intent = ExecutionIntent(
            venue=Venue.HYPERLIQUID,
            mode=MirrorMode.PAPER,
            source_trade_id=trade.trade_id,
            wallet=wallet,
            market=trade.market,
            asset=trade.asset,
            side=trade.side,
            order_type="paper_limit",
            price=trade.price,
            size=round(size, 10),
            notional_usd=round(cap, 6),
            rationale="paper mirror with follower-bankroll size-down and stop-loss/cooldown guardrails",
            metadata=metadata,
        )
        self.state.positions[key] = PaperPosition(
            wallet=wallet,
            market=trade.market,
            asset=trade.asset,
            side=trade.side,
            entry_px=trade.price,
            size=round(size, 10),
            notional_usd=round(cap, 6),
            opened_at=trade.observed_at,
            source_trade_id=trade.trade_id,
        )
        record = DecisionRecord(
            timestamp_utc=trade.observed_at,
            mode=MirrorMode.PAPER,
            venue=Venue.HYPERLIQUID,
            signal=f"{wallet}/{trade.trade_id}",
            decision="paper_mirror_open",
            rationale="risk-capped paper mirror order emitted without live submission",
            receipt=f"paper:{trade.trade_id}",
            outcome="open",
            metadata={"execution_intent": intent.to_dict(), "risk_controls": metadata},
        )
        return PaperMirrorDecision(intent=intent, ledger_record=record)

    def process_mark(self, *, market: str, mark_px: float, timestamp_utc: str) -> list[PaperMirrorDecision]:
        decisions: list[PaperMirrorDecision] = []
        for key, position in list(self.state.positions.items()):
            if position.market != market or not _stop_loss_triggered(position, mark_px, self.config.stop_loss_pct):
                continue
            pnl = _position_pnl(position, mark_px)
            closed = PaperClosedTrade(
                wallet=position.wallet,
                market=position.market,
                source_trade_id=position.source_trade_id,
                opened_at=position.opened_at,
                closed_at=timestamp_utc,
                entry_px=position.entry_px,
                exit_px=mark_px,
                size=position.size,
                realized_pnl_usd=round(pnl, 6),
                reason="stop_loss",
            )
            self.state.closed_trades.append(closed)
            del self.state.positions[key]
            cooldown_until = (_parse_ts(timestamp_utc) + timedelta(minutes=self.config.cooldown_minutes)).isoformat().replace(
                "+00:00", "Z"
            )
            self.state.cooldown_until[key] = cooldown_until
            record = DecisionRecord(
                timestamp_utc=timestamp_utc,
                mode=MirrorMode.PAPER,
                venue=Venue.HYPERLIQUID,
                signal=f"{position.wallet}/{position.source_trade_id}",
                decision="paper_stop_loss",
                rationale="Hyperliquid mark price breached the configured paper stop-loss guard",
                receipt=f"paper-stop:{position.source_trade_id}",
                outcome="loss" if pnl < 0 else "win",
                metadata={
                    "risk_control": "stop_loss",
                    "entry_px": position.entry_px,
                    "mark_px": mark_px,
                    "stop_loss_pct": self.config.stop_loss_pct,
                    "realized_pnl_usd": round(pnl, 6),
                    "cooldown_until": cooldown_until,
                },
            )
            decisions.append(PaperMirrorDecision(intent=None, ledger_record=record))
        return decisions

    def process_close(
        self,
        *,
        wallet: str,
        market: str,
        exit_px: float,
        timestamp_utc: str,
        reason: str = "fixture_exit",
    ) -> PaperMirrorDecision:
        key = _position_key(wallet, market)
        position = self.state.positions.get(key)
        if position is None:
            record = DecisionRecord(
                timestamp_utc=timestamp_utc,
                mode=MirrorMode.PAPER,
                venue=Venue.HYPERLIQUID,
                signal=f"{wallet.lower()}/{market}",
                decision="skip_close_missing_position",
                rationale="fixture close event had no open paper position",
                receipt=None,
                outcome="blocked",
                metadata={"risk_control": "position_state", "market": market},
            )
            return PaperMirrorDecision(intent=None, ledger_record=record)

        pnl = _position_pnl(position, exit_px)
        self.state.closed_trades.append(
            PaperClosedTrade(
                wallet=position.wallet,
                market=position.market,
                source_trade_id=position.source_trade_id,
                opened_at=position.opened_at,
                closed_at=timestamp_utc,
                entry_px=position.entry_px,
                exit_px=exit_px,
                size=position.size,
                realized_pnl_usd=round(pnl, 6),
                reason=reason,
            )
        )
        del self.state.positions[key]
        record = DecisionRecord(
            timestamp_utc=timestamp_utc,
            mode=MirrorMode.PAPER,
            venue=Venue.HYPERLIQUID,
            signal=f"{position.wallet}/{position.source_trade_id}",
            decision="paper_close",
            rationale="fixture paper close records realized outcome without live execution",
            receipt=f"paper-close:{position.source_trade_id}",
            outcome="win" if pnl > 0 else "loss" if pnl < 0 else "flat",
            metadata={
                "risk_control": "paper_exit",
                "entry_px": position.entry_px,
                "exit_px": exit_px,
                "realized_pnl_usd": round(pnl, 6),
                "reason": reason,
            },
        )
        return PaperMirrorDecision(intent=None, ledger_record=record)

    def tearsheet(self) -> dict[str, Any]:
        return build_paper_mirror_tearsheet(self.state)

    def _record_skip(
        self,
        trade: NormalizedTrade,
        *,
        decision: str,
        rationale: str,
        metadata: dict[str, Any],
    ) -> DecisionRecord:
        return DecisionRecord(
            timestamp_utc=trade.observed_at,
            mode=MirrorMode.PAPER,
            venue=Venue.HYPERLIQUID,
            signal=f"{trade.wallet.lower()}/{trade.trade_id}",
            decision=decision,
            rationale=rationale,
            receipt=None,
            outcome="blocked",
            metadata=metadata,
        )


def build_paper_mirror_tearsheet(state: PaperMirrorState) -> dict[str, Any]:
    closed = state.closed_trades
    wins = [trade for trade in closed if trade.realized_pnl_usd > 0]
    losses = [trade for trade in closed if trade.realized_pnl_usd < 0]
    total = sum(trade.realized_pnl_usd for trade in closed)
    return {
        "closed_trades": len(closed),
        "open_positions": len(state.positions),
        "wins": len(wins),
        "losses": len(losses),
        "realized_pnl_usd": round(total, 6),
        "expectancy_usd": round(total / len(closed), 6) if closed else 0.0,
        "cooldowns_active": len(state.cooldown_until),
        "closed": [trade.__dict__ for trade in closed],
    }


def replay_paper_mirror_fixture(
    *,
    fixture_path: Path | str = DEFAULT_PAPER_MIRROR_FIXTURE,
    rankings: list[WalletRanking],
    config: PaperMirrorConfig | None = None,
) -> PaperMirrorReplay:
    engine = PaperMirrorEngine(rankings=rankings, config=config)
    decisions: list[PaperMirrorDecision] = []
    for row in _load_fixture_rows(fixture_path):
        row_type = row.get("type")
        if row_type == "trade":
            decisions.append(engine.process_trade(_trade_from_row(row)))
        elif row_type == "mark":
            decisions.extend(
                engine.process_mark(
                    market=str(row["market"]),
                    mark_px=float(row["mark_px"]),
                    timestamp_utc=str(row["timestamp_utc"]),
                )
            )
        elif row_type == "close":
            decisions.append(
                engine.process_close(
                    wallet=str(row["wallet"]).lower(),
                    market=str(row["market"]),
                    exit_px=float(row["exit_px"]),
                    timestamp_utc=str(row["timestamp_utc"]),
                    reason=str(row.get("reason") or "fixture_exit"),
                )
            )
        else:
            raise ValueError(f"unsupported paper mirror fixture row: {row_type!r}")
    return PaperMirrorReplay(decisions=decisions, tearsheet=engine.tearsheet(), state=engine.state)


def _load_fixture_rows(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{line_no}: invalid json") from e
    return rows


def _trade_from_row(row: dict[str, Any]) -> NormalizedTrade:
    return NormalizedTrade(
        venue=Venue.HYPERLIQUID,
        trade_id=str(row["trade_id"]),
        wallet=str(row["wallet"]).lower(),
        market=str(row["market"]),
        asset=str(row["asset"]),
        side=TradeSide(str(row["side"])),
        price=float(row["price"]),
        size=float(row["size"]),
        notional_usd=float(row["notional_usd"]),
        observed_at=str(row["observed_at"]),
        raw=dict(row.get("raw") or row),
    )


def _position_key(wallet: str, market: str) -> str:
    return f"{wallet.lower()}::{market}"


def _stop_loss_triggered(position: PaperPosition, mark_px: float, stop_loss_pct: float) -> bool:
    if position.side in {TradeSide.BUY, TradeSide.LONG}:
        return mark_px <= position.entry_px * (1.0 - stop_loss_pct)
    return mark_px >= position.entry_px * (1.0 + stop_loss_pct)


def _position_pnl(position: PaperPosition, exit_px: float) -> float:
    direction = 1.0 if position.side in {TradeSide.BUY, TradeSide.LONG} else -1.0
    return (exit_px - position.entry_px) * position.size * direction


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
