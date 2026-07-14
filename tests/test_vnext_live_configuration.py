from __future__ import annotations

import json

import pytest

from stonks_cli.vnext.live_configuration import LIVE_CONFIGURATION_VERSION, load_deferred_live_configuration


def test_separate_private_live_configuration_accepts_only_disabled_execution_mode(tmp_path):
    primary_path = tmp_path / "config.json"
    live_path = tmp_path / "live.json"
    live_path.write_text(json.dumps({"version": LIVE_CONFIGURATION_VERSION, "execution_mode": "disabled"}), encoding="utf-8")
    live_path.chmod(0o600)

    configuration = load_deferred_live_configuration(live_path, primary_path)

    assert configuration.path == live_path
    assert configuration.execution_mode == "disabled"


@pytest.mark.parametrize(
    "contents",
    [
        "not-json",
        json.dumps({}),
        json.dumps({"version": 2, "execution_mode": "disabled"}),
        json.dumps({"version": LIVE_CONFIGURATION_VERSION, "execution_mode": "live"}),
        json.dumps({"version": LIVE_CONFIGURATION_VERSION, "execution_mode": None}),
    ],
)
def test_live_configuration_fails_closed_for_malformed_external_data(tmp_path, contents):
    live_path = tmp_path / "live.json"
    live_path.write_text(contents, encoding="utf-8")
    live_path.chmod(0o600)

    with pytest.raises(ValueError, match="live configuration"):
        load_deferred_live_configuration(live_path, tmp_path / "config.json")


def test_live_configuration_requires_a_distinct_private_regular_file(tmp_path):
    primary_path = tmp_path / "config.json"
    primary_path.write_text(json.dumps({"version": LIVE_CONFIGURATION_VERSION, "execution_mode": "disabled"}), encoding="utf-8")
    primary_path.chmod(0o600)
    public_path = tmp_path / "live.json"
    public_path.write_text(primary_path.read_text(encoding="utf-8"), encoding="utf-8")
    public_path.chmod(0o644)

    with pytest.raises(ValueError, match="differ from"):
        load_deferred_live_configuration(primary_path, primary_path)
    with pytest.raises(PermissionError, match="owner-only"):
        load_deferred_live_configuration(public_path, primary_path)
    with pytest.raises(FileNotFoundError, match="required"):
        load_deferred_live_configuration(tmp_path / "missing.json", primary_path)
