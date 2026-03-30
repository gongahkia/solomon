from __future__ import annotations

import pytest

from stonks_cli.commands import do_alert_add


def test_alert_add_rejects_unknown_condition(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    with pytest.raises(ValueError, match="unknown alert condition"):
        do_alert_add("AAPL", "not_a_real_condition", 1.0)
