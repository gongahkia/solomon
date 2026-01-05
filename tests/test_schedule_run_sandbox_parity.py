from apscheduler.schedulers.blocking import BlockingScheduler

from stonks_cli.config import AppConfig
from stonks_cli.scheduler.run import build_scheduler


def test_schedule_run_sandbox_is_passed_to_run_once(monkeypatch, tmp_path):
    captured = {}

    def fake_add_job(self, func, *args, **kwargs):  # noqa: ANN001
        captured["job"] = func
        return None

    monkeypatch.setattr(BlockingScheduler, "add_job", fake_add_job)

    import stonks_cli.scheduler.run as sched_run

    def record_run_once(*args, **kwargs):  # noqa: ANN001
        captured["sandbox"] = kwargs.get("sandbox")
        return tmp_path / "report.txt"

    monkeypatch.setattr(sched_run, "run_once", record_run_once)

    cfg = AppConfig()
    build_scheduler(cfg, out_dir=tmp_path, sandbox=True)
    captured["job"]()
    assert captured.get("sandbox") is True
