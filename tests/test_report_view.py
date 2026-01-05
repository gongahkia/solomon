from pathlib import Path

import pytest

from stonks_cli.commands import do_report_view
from stonks_cli.storage import save_last_run


def test_do_report_view_uses_last_report_when_path_is_none(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))

    report_path = tmp_path / "report_latest.txt"
    report_path.write_text("hello", encoding="utf-8")
    save_last_run(["AAPL"], report_path)

    out = do_report_view(None)
    assert out["path"] == str(report_path)
    assert out["text"] == "hello"


def test_do_report_view_raises_when_no_last_report(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        do_report_view(None)
