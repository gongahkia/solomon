from __future__ import annotations

from pathlib import Path

from stonks_cli.polymarket.research import build_research_prompt, generate_thesis, load_theses, save_thesis


def test_research_prompt_contains_four_article_checks() -> None:
    prompt = build_research_prompt({"market_id": "m1", "question": "Will BTC close higher?"})

    assert "base_rate" in prompt
    assert "recent_news" in prompt
    assert "whale_presence" in prompt
    assert "crowd_disposition" in prompt


def test_dry_run_thesis_is_cached_without_network(tmp_path: Path) -> None:
    thesis = generate_thesis(
        {
            "market_id": "m1",
            "token_id": "YES1",
            "question": "Will BTC close higher?",
            "target_wallet_count": 2,
        },
        dry_run=True,
    )
    cache = tmp_path / "theses.json"
    save_thesis(thesis, cache)

    loaded = load_theses(cache)

    assert len(loaded) == 1
    assert loaded[0].market_id == "m1"
    assert loaded[0].checks["whale_presence"] is True
    assert loaded[0].passed_checks == 1
