from __future__ import annotations

from stonks_cli.whalemirror.attribution import (
    DEFAULT_ATTRIBUTION_FIXTURE,
    load_attribution_fixture,
    rank_wallets,
    rank_wallets_from_fixture,
    render_wallet_ranking_markdown,
)


def test_load_attribution_fixture_splits_trades_and_funding():
    trades, fundings = load_attribution_fixture(DEFAULT_ATTRIBUTION_FIXTURE)

    assert len(trades) == 6
    assert len(fundings) == 2
    assert trades[0].wallet == "0xaaa0000000000000000000000000000000000001"
    assert trades[0].gross_pnl_usd == 10.0
    assert fundings[0].funding_usd == -1.0


def test_rank_wallets_includes_funding_leverage_survivorship_and_decay():
    trades, fundings = load_attribution_fixture(DEFAULT_ATTRIBUTION_FIXTURE)

    rankings = rank_wallets(trades, fundings)
    first = rankings[0]
    high_leverage = next(r for r in rankings if r.metrics.wallet.startswith("0xbbb"))

    assert first.metrics.wallet == "0xaaa0000000000000000000000000000000000001"
    assert first.metrics.sample_size == 3
    assert first.metrics.funding_adjusted_pnl == 12.55
    assert first.metrics.survivorship_adjusted_pnl == 7.53
    assert first.leverage_adjusted_pnl_usd == 5.8
    assert len(first.rolling_sharpe) == 2
    assert "funding_costs_included" in first.metrics.caveats
    assert "manual_top_10_validation_pending:#15" in first.metrics.caveats
    assert high_leverage.metrics.survivorship_adjusted_pnl == 3.8
    assert "high_leverage:20x" in high_leverage.metrics.caveats


def test_ranking_limit_defaults_to_top_100_but_can_be_limited():
    rankings = rank_wallets_from_fixture(DEFAULT_ATTRIBUTION_FIXTURE, limit=2)

    assert len(rankings) == 2
    assert rankings[0].metrics.survivorship_adjusted_pnl >= rankings[1].metrics.survivorship_adjusted_pnl


def test_rendered_ranking_uses_supported_metric_language_not_alpha_claims():
    rankings = rank_wallets_from_fixture(DEFAULT_ATTRIBUTION_FIXTURE)

    markdown = render_wallet_ranking_markdown(rankings)

    assert "Expectancy USD" in markdown
    assert "Sharpe" in markdown
    assert "Funding-adjusted PnL" in markdown
    assert "Survivorship-adjusted PnL" in markdown
    assert "manual_top_10_validation_pending:#15" in markdown
    assert "alpha" not in markdown.lower().replace("not an alpha claim", "")
