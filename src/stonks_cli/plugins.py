from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Callable

from stonks_cli.config import AppConfig
from stonks_cli.analysis.strategy import Recommendation


StrategyFn = Callable[[object], object]
ProviderFactory = Callable[[AppConfig, str], object]


def _validated_strategy(spec: str, name: str, fn: StrategyFn) -> StrategyFn:
    def wrapper(df: object) -> Recommendation:
        out = fn(df)
        if not isinstance(out, Recommendation):
            raise TypeError(
                f"plugin strategy '{name}' from '{spec}' must return Recommendation, got {type(out).__name__}"
            )
        return out

    return wrapper


@dataclass(frozen=True)
class PluginRegistry:
    strategies: dict[str, StrategyFn]
    provider_factories: dict[str, ProviderFactory]


@dataclass(frozen=True)
class PluginLoadSummary:
    registry: PluginRegistry
    ok: list[str]
    errors: dict[str, str]


def _load_module(spec: str) -> ModuleType:
    s = (spec or "").strip()
    if not s:
        raise ValueError("plugin spec must be non-empty")

    looks_like_path = s.endswith(".py") or "/" in s or "\\" in s
    if looks_like_path:
        path = Path(s).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"plugin file not found: {path}")
        mod_name = f"stonks_plugin_{path.stem}_{abs(hash(str(path)))}"
        module_spec = importlib.util.spec_from_file_location(mod_name, str(path))
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"failed to load plugin module from {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    return importlib.import_module(s)


@lru_cache(maxsize=64)
def load_plugins(plugin_specs: tuple[str, ...]) -> PluginRegistry:
    strategies: dict[str, StrategyFn] = {}
    provider_factories: dict[str, ProviderFactory] = {}

    for spec in plugin_specs:
        module = _load_module(spec)

        mod_strats = getattr(module, "STONKS_STRATEGIES", None)
        if isinstance(mod_strats, dict):
            for name, fn in mod_strats.items():
                if not isinstance(name, str) or not name.strip():
                    continue
                if callable(fn):
                    strategies[name] = _validated_strategy(spec, name, fn)

        mod_providers = getattr(module, "STONKS_PROVIDER_FACTORIES", None)
        if isinstance(mod_providers, dict):
            for name, factory in mod_providers.items():
                if not isinstance(name, str) or not name.strip():
                    continue
                if callable(factory):
                    provider_factories[name] = factory

    return PluginRegistry(strategies=strategies, provider_factories=provider_factories)


def load_plugins_best_effort(plugin_specs: tuple[str, ...]) -> PluginLoadSummary:
    strategies: dict[str, StrategyFn] = {}
    provider_factories: dict[str, ProviderFactory] = {}
    ok: list[str] = []
    errors: dict[str, str] = {}

    for spec in plugin_specs:
        try:
            module = _load_module(spec)
            ok.append(spec)
        except Exception as e:
            errors[spec] = str(e)
            continue

        mod_strats = getattr(module, "STONKS_STRATEGIES", None)
        if isinstance(mod_strats, dict):
            for name, fn in mod_strats.items():
                if not isinstance(name, str) or not name.strip():
                    continue
                if callable(fn):
                    strategies[name] = _validated_strategy(spec, name, fn)

        mod_providers = getattr(module, "STONKS_PROVIDER_FACTORIES", None)
        if isinstance(mod_providers, dict):
            for name, factory in mod_providers.items():
                if not isinstance(name, str) or not name.strip():
                    continue
                if callable(factory):
                    provider_factories[name] = factory

    return PluginLoadSummary(
        registry=PluginRegistry(strategies=strategies, provider_factories=provider_factories),
        ok=ok,
        errors=errors,
    )


def registry_for_config(cfg: AppConfig) -> PluginRegistry:
    return load_plugins(tuple(cfg.plugins or []))
