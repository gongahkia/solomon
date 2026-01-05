import json

from stonks_cli.commands import do_doctor


def test_doctor_output_keys_smoke(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"tickers": []}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    out = do_doctor()
    assert out.get("config_loaded") == "ok"
    assert "config_path" in out
    assert "cache_dir" in out
    assert "state_dir" in out
