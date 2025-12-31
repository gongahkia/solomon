from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger

from stonks_cli import __version__
from stonks_cli.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
from rich.console import Console

from stonks_cli.analysis.output import AnalysisArtifacts
from stonks_cli.config import AppConfig, config_path, load_config, save_config, save_default_config, update_config_field
from stonks_cli.pipeline import compute_results, provider_for_config, run_once, select_strategy
from stonks_cli.scheduler.run import SchedulerHandle, run_scheduler, start_scheduler_in_thread
from stonks_cli.data.providers import CsvProvider, StooqProvider
from stonks_cli.reporting.backtest_report import BacktestRow, write_backtest_report
from stonks_cli.reporting.json_report import write_json_report
from stonks_cli.reporting.report import write_text_report
from stonks_cli.storage import get_history_record, get_last_report_path, list_history, save_last_run


def do_version() -> str:
    return __version__


def do_ollama_check() -> str:
    cfg = load_config()
    host = cfg.model.host
    try:
        from ollama import Client

        client = Client(host=host)
        try:
            models = client.list()  # type: ignore[attr-defined]
        except AttributeError:
            import ollama

            models = ollama.list()

        # 'models' is often an object with a .models list.
        items = getattr(models, "models", None)
        if items is None and isinstance(models, dict):
            items = models.get("models")
        n = len(items) if items else 0
        return f"ok host={host} models={n}"
    except Exception as e:
        return f"error host={host} error={e}"


def do_llm_check(
    *,
    backend: str | None = None,
    model: str | None = None,
    host: str | None = None,
    path: str | None = None,
    offline: bool | None = None,
) -> str:
    """Check LLM backend connectivity / availability.

    This is best-effort and intentionally lightweight.
    """

    cfg = load_config().model
    use_backend = (backend or cfg.backend or "auto").lower()
    use_model = model or cfg.model
    use_host = host or cfg.host
    use_path = path if path is not None else cfg.path
    use_offline = bool(cfg.offline if offline is None else offline)

    if use_backend in {"ollama", "auto"} and not use_offline:
        # Reuse the existing check, but honor host override.
        try:
            from ollama import Client

            client = Client(host=use_host)
            try:
                models = client.list()  # type: ignore[attr-defined]
            except AttributeError:
                import ollama

                models = ollama.list()

            items = getattr(models, "models", None)
            if items is None and isinstance(models, dict):
                items = models.get("models")
            n = len(items) if items else 0
            return f"ok backend=ollama host={use_host} models={n}"
        except Exception as e:
            return f"error backend=ollama host={use_host} error={e}"

    # For local backends, validate dependency + local path. Avoid actually loading large models.
    if use_backend == "llama_cpp" or (use_backend == "auto" and use_offline):
        try:
            import importlib.util
            from pathlib import Path

            if importlib.util.find_spec("llama_cpp") is None:
                return "error backend=llama_cpp error=missing_dependency (install -e '.[llama-cpp]')"
            if not use_path:
                return "error backend=llama_cpp error=missing_model_path (set model.path to a GGUF file)"
            p = Path(use_path).expanduser()
            if not p.exists():
                return f"error backend=llama_cpp error=model_not_found path={p}"
            return f"ok backend=llama_cpp path={p}"
        except Exception as e:
            return f"error backend=llama_cpp error={e}"

    if use_backend == "mlx":
        try:
            import importlib.util
            from pathlib import Path

            if importlib.util.find_spec("mlx_lm") is None:
                return "error backend=mlx error=missing_dependency (install -e '.[mlx]')"
            if use_offline:
                if not use_path:
                    return "error backend=mlx error=missing_model_path (set model.path to a local directory)"
                p = Path(use_path).expanduser()
                if not p.exists():
                    return f"error backend=mlx error=model_not_found path={p}"
            return f"ok backend=mlx model={use_path or use_model} offline={use_offline}"
        except Exception as e:
            return f"error backend=mlx error={e}"

    if use_backend == "transformers":
        try:
            import importlib.util
            from pathlib import Path

            if importlib.util.find_spec("transformers") is None:
                return "error backend=transformers error=missing_dependency (install -e '.[transformers]')"
            if use_offline:
                if not use_path:
                    return "error backend=transformers error=missing_model_path (set model.path to a local directory)"
                p = Path(use_path).expanduser()
                if not p.exists():
                    return f"error backend=transformers error=model_not_found path={p}"
            return f"ok backend=transformers model={use_path or use_model} offline={use_offline}"
        except Exception as e:
            return f"error backend=transformers error={e}"

    if use_backend == "onnx":
        try:
            import importlib.util

            if importlib.util.find_spec("onnxruntime") is None:
                return "error backend=onnx error=missing_dependency (pip install onnxruntime)"
            return "ok backend=onnx"
        except Exception as e:
            return f"error backend=onnx error={e}"

    return f"error backend={use_backend} error=unsupported_backend"


def do_doctor() -> dict[str, str]:
    cfg = load_config()
    out: dict[str, str] = {}
    try:
        out["config_path"] = str(config_path())
        out["config_loaded"] = "ok"
    except Exception as e:
        out["config_loaded"] = f"error: {e}"

    # Data provider check (best-effort): uses configured provider for first ticker.
    try:
        tickers = cfg.tickers or []
        if not tickers:
            out["data_provider"] = "skipped (no tickers)"
        else:
            provider = provider_for_config(cfg, tickers[0])
            series = provider.fetch_daily(tickers[0])
            out["data_provider"] = "ok" if not series.df.empty else "no_rows"
    except Exception as e:
        out["data_provider"] = f"error: {e}"

    out["llm"] = do_llm_check()
    return out


def do_config_where() -> Path:
    return config_path()


def do_config_init(path: Path | None) -> Path:
    return save_default_config(path)


def do_config_show() -> str:
    cfg = load_config()
    return cfg.model_dump_json(indent=2)


def do_config_set(field_path: str, value) -> str:
    cfg = load_config()
    updated = update_config_field(cfg, field_path, value)
    save_config(updated)
    return updated.model_dump_json(indent=2)


def do_analyze(tickers: list[str] | None, out_dir: Path, *, sandbox: bool = False) -> Path:
    artifacts = do_analyze_artifacts(tickers, out_dir=out_dir, json_out=False, sandbox=sandbox)
    return artifacts.report_path


def do_analyze_artifacts(
    tickers: list[str] | None,
    *,
    out_dir: Path,
    json_out: bool,
    sandbox: bool = False,
) -> AnalysisArtifacts:
    cfg = load_config()
    if tickers:
        cfg = cfg.model_copy(update={"tickers": tickers})

    console = Console()
    results, portfolio = compute_results(cfg, console)
    report_path = write_text_report(results, out_dir=out_dir, portfolio=portfolio)

    json_path = None
    if json_out:
        json_path = out_dir / f"{report_path.stem}.json"
        write_json_report(results, out_path=json_path, portfolio=portfolio)

    if not sandbox:
        save_last_run(cfg.tickers, report_path, json_path=json_path)

    return AnalysisArtifacts(report_path=report_path, json_path=json_path, portfolio=portfolio, results=results)


def do_bench(tickers: list[str] | None, *, iterations: int = 5, warmup: int = 1) -> str:
    cfg = load_config()
    if tickers:
        cfg = cfg.model_copy(update={"tickers": tickers})

    # Avoid mixing benchmark timing with I/O-heavy report generation.
    console = Console()

    for _ in range(max(0, warmup)):
        compute_results(cfg, console)

    timings: list[float] = []
    for _ in range(iterations):
        start = perf_counter()
        compute_results(cfg, console)
        timings.append(perf_counter() - start)

    timings_sorted = sorted(timings)
    avg = sum(timings) / len(timings)
    p50 = timings_sorted[len(timings_sorted) // 2]
    p95 = timings_sorted[max(0, int(len(timings_sorted) * 0.95) - 1)]
    return (
        f"benchmark tickers={len(cfg.tickers)} iterations={iterations} "
        f"avg={avg:.4f}s p50={p50:.4f}s p95={p95:.4f}s"
    )


def do_backtest(
    tickers: list[str] | None,
    *,
    start: str | None,
    end: str | None,
    out_dir: Path,
) -> Path:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    strategy_fn = select_strategy(cfg)

    rows: list[BacktestRow] = []
    for t in use:
        provider = provider_for_config(cfg, t)
        series = provider.fetch_daily(t)
        df = series.df
        if start:
            df = df.loc[start:]
        if end:
            df = df.loc[:end]
        bt = walk_forward_backtest(df, strategy_fn=strategy_fn, min_history_rows=cfg.risk.min_history_days)
        metrics = compute_backtest_metrics(bt.equity)
        rows.append(BacktestRow(ticker=series.ticker, metrics=metrics))

    return write_backtest_report(rows, out_dir)


def do_report_open() -> Path:
    p = get_last_report_path()
    if p is None:
        raise FileNotFoundError("No last report recorded")
    return p


def do_history_list(limit: int = 20):
    return list_history(limit=limit)


def do_history_show(index: int, *, limit: int = 2000):
    return get_history_record(index, limit=limit)


def do_schedule_once(out_dir: Path, *, sandbox: bool = False) -> Path:
    cfg = load_config()
    return run_once(cfg, out_dir=out_dir, sandbox=sandbox)


def do_schedule_run(out_dir: Path) -> None:
    cfg = load_config()
    run_scheduler(cfg, out_dir=out_dir)


@dataclass(frozen=True)
class ScheduleStatus:
    cron: str
    next_run: str | None
    error: str | None


def do_schedule_status() -> ScheduleStatus:
    cfg: AppConfig = load_config()
    try:
        trigger = CronTrigger.from_crontab(cfg.schedule.cron)
        next_dt = trigger.get_next_fire_time(None, datetime.now())
        return ScheduleStatus(cron=cfg.schedule.cron, next_run=str(next_dt), error=None)
    except Exception as e:
        return ScheduleStatus(cron=cfg.schedule.cron, next_run=None, error=str(e))


def do_schedule_start_background(out_dir: Path) -> SchedulerHandle:
    cfg = load_config()
    return start_scheduler_in_thread(cfg, out_dir=out_dir)


def do_data_fetch(tickers: list[str] | None) -> list[str]:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    fetched: list[str] = []
    for t in use:
        override = cfg.ticker_overrides.get(t)
        data_cfg = override.data if override else cfg.data
        if data_cfg.provider == "csv":
            if not data_cfg.csv_path:
                raise ValueError(f"csv provider requires csv_path for {t}")
            provider = CsvProvider(data_cfg.csv_path)
        else:
            provider = StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)
        provider.fetch_daily(t)
        fetched.append(t)
    return fetched


def do_data_verify(tickers: list[str] | None) -> dict[str, str]:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    out: dict[str, str] = {}
    for t in use:
        try:
            override = cfg.ticker_overrides.get(t)
            data_cfg = override.data if override else cfg.data
            if data_cfg.provider == "csv":
                if not data_cfg.csv_path:
                    raise ValueError("csv_path missing")
                provider = CsvProvider(data_cfg.csv_path)
            else:
                provider = StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)
            series = provider.fetch_daily(t)
            out[t] = "ok" if not series.df.empty else "no_rows"
        except Exception as e:
            out[t] = f"error: {e}"
    return out
