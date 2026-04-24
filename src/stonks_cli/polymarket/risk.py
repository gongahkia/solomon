from __future__ import annotations

from stonks_cli.config import AppConfig
from stonks_cli.polymarket.models import PaperAccount, ProposalDecision, TradeProposal


def build_trade_proposal(cfg: AppConfig, account: PaperAccount, scan) -> ProposalDecision:
    reasons: list[str] = []
    if not cfg.polymarket.auto_trade_enabled:
        reasons.append("auto_trade_disabled")
    if scan.status != "PASS":
        reasons.append("scan_not_pass")
    if scan.token_id is None:
        reasons.append("missing_token")
    if scan.midpoint is None or scan.midpoint <= 0 or scan.midpoint >= 1:
        reasons.append("invalid_midpoint")
    if scan.score < cfg.polymarket.auto_trade_min_score:
        reasons.append("score_below_threshold")
    if scan.target_wallet_count < cfg.polymarket.auto_trade_min_target_wallets:
        reasons.append("wallet_signal_below_threshold")
    if any(position.token_id == scan.token_id for position in account.positions):
        reasons.append("position_already_open")
    if len(account.positions) >= cfg.polymarket.max_open_positions:
        reasons.append("max_open_positions_reached")
    if reasons:
        return ProposalDecision(accepted=False, reasons=reasons)

    available_cash = max(0.0, account.cash)
    max_notional = available_cash * cfg.polymarket.max_position_fraction
    reserve_cash = available_cash * cfg.polymarket.min_cash_reserve_fraction
    if max_notional <= 0:
        return ProposalDecision(accepted=False, reasons=["no_cash_available"])
    if available_cash - max_notional < reserve_cash:
        max_notional = max(0.0, available_cash - reserve_cash)
    if max_notional <= 0:
        return ProposalDecision(accepted=False, reasons=["cash_reserve_guard"])

    shares = round(max_notional / float(scan.midpoint), 6)
    if shares <= 0:
        return ProposalDecision(accepted=False, reasons=["shares_rounded_to_zero"])

    target = min(0.99, float(scan.midpoint) + cfg.polymarket.take_profit_price_delta)
    stop = max(0.01, float(scan.midpoint) - cfg.polymarket.stop_loss_price_delta)
    proposal = TradeProposal(
        token_id=scan.token_id,
        market_id=scan.market_id,
        slug=scan.slug,
        outcome=scan.outcome,
        side="BUY",
        price=float(scan.midpoint),
        shares=shares,
        notional=round(shares * float(scan.midpoint), 6),
        score=float(scan.score),
        target_price=round(target, 6),
        stop_price=round(stop, 6),
        reason=f"score={scan.score:.2f}|wallets={scan.target_wallet_count}",
    )
    return ProposalDecision(accepted=True, reasons=[], proposal=proposal)
