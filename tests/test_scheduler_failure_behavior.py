import json

from apscheduler.schedulers.blocking import BlockingScheduler

from stonks_cli import storage
from stonks_cli.config import AppConfig
from stonks_cli.scheduler.run import build_scheduler


def test_scheduler_job_failure_is_logged_and_does_not_raise(monkeypatch, tmp_path):
    # Keep state writes isolated.
    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)

    captured = {}

    def fake_add_job(self, func, *args, **kwargs):  # noqa: ANN001
        captured["job"] = func
        return None

    monkeypatch.setattr(BlockingScheduler, "add_job", fake_add_job)

    import stonks_cli.scheduler.run as sched_run

    def boom(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(sched_run, "run_once", boom)

    cfg = AppConfig()
    build_scheduler(cfg, out_dir=tmp_path)
    captured["job"]()

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["last_failure"]["where"] == "scheduler"
    assert "boom" in state["last_failure"]["error"]
