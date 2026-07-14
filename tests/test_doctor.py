from __future__ import annotations

from stonks_cli.commands import do_doctor


def test_doctor_includes_paths_and_research_guards(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    out = do_doctor()
    assert "config_path" in out
    assert "cache_dir" in out
    assert "state_dir" in out
    assert "research_paper_guards" in out
    assert out["research_paper_guards"] == "clear"
    assert "research_live_guards" in out
    assert "live_trading_not_armed" in out["research_live_guards"]
