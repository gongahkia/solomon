from __future__ import annotations

from stonks_cli.config import AppConfig
from stonks_cli.polymarket.models import PaperAccount, ProposalDecision, TradeProposal


def kelly_fraction_for_binary(p_win: float, entry_price: float) -> float:
    """Kelly fraction for a 0/1 contract bought at entry_price with win-prob p_win.
    f* = p - (1-p)*entry/(1-entry). Clamped to [0, 1]."""
    if entry_price <= 0 or entry_price >= 1 or p_win <= 0 or p_win >= 1:
        return 0.0
    f = p_win - (1.0 - p_win) * entry_price / (1.0 - entry_price)
    return max(0.0, min(1.0, f))


def vol_target_fraction_for_binary(target_per_trade: float, entry_price: float) -> float:
    """Carver-style inverse-volatility sizing for a Bernoulli payoff.
    σ = sqrt(p*(1-p)); fraction = target / σ. Clamped to [0, 1]."""
    import math

    if entry_price <= 0 or entry_price >= 1 or target_per_trade <= 0:
        return 0.0
    sigma = math.sqrt(entry_price * (1.0 - entry_price))
    if sigma <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, target_per_trade / sigma))


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
    cap_fraction = cfg.polymarket.max_position_fraction
    has_wallet_signal = getattr(scan, "target_wallet_count", 0) > 0 and getattr(scan, "target_trade_count", 0) > 0
    if cfg.polymarket.kelly_sizing_enabled and has_wallet_signal:
        # win-prob proxy from target wallets' aggregate behavior; conservative floor at 0.5 (parity)
        # we don't have the per-wallet win_rate on the scan; assume 0.6 for any wallet-confirmed signal
        # and let user tighten with min_win_rate at rank time. crude but additive over plain max_position_fraction.
        p_win = 0.6
        kelly = kelly_fraction_for_binary(p_win, float(scan.midpoint)) * cfg.polymarket.kelly_fraction
        cap_fraction = min(cap_fraction, kelly) if kelly > 0 else 0.0
    elif cfg.polymarket.vol_target_enabled:
        vt = vol_target_fraction_for_binary(cfg.polymarket.vol_target_per_trade, float(scan.midpoint))
        cap_fraction = min(cap_fraction, vt) if vt > 0 else 0.0
    max_notional = available_cash * cap_fraction
    reserve_cash = available_cash * cfg.polymarket.min_cash_reserve_fraction
    if max_notional <= 0:
        return ProposalDecision(accepted=False, reasons=["no_cash_available"])
    if available_cash - max_notional < reserve_cash:
        max_notional = max(0.0, available_cash - reserve_cash)
    if max_notional <= 0:
        return ProposalDecision(accepted=False, reasons=["cash_reserve_guard"])

    mp = getattr(scan, "microprice", None)
    entry_price = float(mp) if (cfg.polymarket.use_microprice_for_entry and mp and 0 < mp < 1) else float(scan.midpoint)
    shares = round(max_notional / entry_price, 6)
    if shares <= 0:
        return ProposalDecision(accepted=False, reasons=["shares_rounded_to_zero"])

    target = min(0.99, entry_price + cfg.polymarket.take_profit_price_delta)
    stop = max(0.01, entry_price - cfg.polymarket.stop_loss_price_delta)
    proposal = TradeProposal(
        token_id=scan.token_id,
        market_id=scan.market_id,
        slug=scan.slug,
        outcome=scan.outcome,
        side="BUY",
        price=entry_price,
        shares=shares,
        notional=round(shares * entry_price, 6),
        score=float(scan.score),
        target_price=round(target, 6),
        stop_price=round(stop, 6),
        reason=f"score={scan.score:.2f}|wallets={scan.target_wallet_count}",
    )
    return ProposalDecision(accepted=True, reasons=[], proposal=proposal)
