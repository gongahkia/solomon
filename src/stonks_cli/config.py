from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_path

from stonks_cli.errors import ProfileError, ProviderError
from stonks_cli.types import Currency, DrawdownResponsePolicy

_PROFILE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_LLM_PROVIDERS = frozenset(("ollama", "openai", "anthropic", "gemini"))
_BUDGET_PERIODS = frozenset(("none", "daily", "monthly"))


@dataclass(frozen=True)
class DividendSettings:
    allow_explicit_credit: bool = False
    allow_currency_conversion: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.allow_explicit_credit, bool):
            raise ProfileError("dividend explicit credit setting must be boolean")
        if not isinstance(self.allow_currency_conversion, bool):
            raise ProfileError("dividend currency conversion setting must be boolean")
        if self.allow_currency_conversion and not self.allow_explicit_credit:
            raise ProfileError("dividend currency conversion requires explicit credit")


@dataclass(frozen=True)
class DrawdownSettings:
    warning_threshold: str = "0.25"
    response_policy: DrawdownResponsePolicy = DrawdownResponsePolicy.ALERT_ONLY
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.warning_threshold, str) or not self.warning_threshold.strip():
            raise ProfileError("drawdown warning threshold must be decimal")
        try:
            threshold = Decimal(self.warning_threshold)
        except InvalidOperation as error:
            raise ProfileError("drawdown warning threshold must be decimal") from error
        if not threshold.is_finite() or not Decimal("0") < threshold < Decimal("1"):
            raise ProfileError("drawdown warning threshold must be between zero and one")
        try:
            policy = DrawdownResponsePolicy(self.response_policy)
        except ValueError as error:
            raise ProfileError("drawdown response policy is invalid") from error
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("drawdown settings version must be a positive integer")
        object.__setattr__(self, "warning_threshold", format(threshold, "f"))
        object.__setattr__(self, "response_policy", policy)

    @property
    def threshold(self) -> Decimal:
        return Decimal(self.warning_threshold)


@dataclass(frozen=True)
class LLMSettings:
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_local_only: bool = False
    budget_period: str = "none"
    budget_limit_sgd: str | None = None
    input_cost_per_million_sgd: str = "0"
    output_cost_per_million_sgd: str = "0"
    max_output_tokens: int = 600
    allow_cloud: bool = False

    def __post_init__(self) -> None:
        if self.provider is None:
            if self.model is not None or self.api_key_env is not None:
                raise ProfileError("LLM model and key environment require a provider")
            return
        provider = self.provider.strip().lower()
        if provider not in _LLM_PROVIDERS:
            raise ProfileError("LLM provider is invalid")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 256:
            raise ProfileError("LLM model is required")
        if self.api_key_env is not None and not _ENVIRONMENT_VARIABLE.fullmatch(self.api_key_env):
            raise ProfileError("LLM key environment variable is invalid")
        if self.budget_period not in _BUDGET_PERIODS:
            raise ProfileError("LLM budget period is invalid")
        if not isinstance(self.max_output_tokens, int) or not 1 <= self.max_output_tokens <= 4096:
            raise ProfileError("LLM max output tokens must be between 1 and 4096")
        try:
            from decimal import Decimal

            input_cost = Decimal(self.input_cost_per_million_sgd)
            output_cost = Decimal(self.output_cost_per_million_sgd)
            limit = None if self.budget_limit_sgd is None else Decimal(self.budget_limit_sgd)
        except Exception as error:
            raise ProfileError("LLM budget values must be decimal") from error
        if input_cost < 0 or output_cost < 0 or (limit is not None and limit <= 0):
            raise ProfileError("LLM budget values must be positive")
        if self.budget_period == "none" and limit is not None:
            raise ProfileError("LLM budget limit requires a daily or monthly period")
        if self.budget_period != "none" and limit is None:
            raise ProfileError("LLM budget period requires a limit")
        if provider != "ollama" and not self.allow_cloud:
            raise ProfileError("cloud LLM provider requires explicit privacy acknowledgement")
        if provider == "ollama" and not self.ollama_local_only:
            raise ProfileError("Ollama requires explicit local-only acknowledgement")
        parsed = urlsplit(self.ollama_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ProfileError("Ollama URL must be a loopback HTTP endpoint")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", self.model.strip())

    @property
    def enabled(self) -> bool:
        return self.provider is not None


def app_root() -> Path:
    override = __import__("os").environ.get("STONKS_CLI_HOME")
    return (
        Path(override).expanduser().resolve()
        if override
        else user_data_path("stonks-cli", appauthor=False)
    )


def validate_profile_name(name: str) -> str:
    if not _PROFILE.fullmatch(name):
        raise ProfileError("profile must match [a-z][a-z0-9_-]{0,63}")
    return name


@dataclass(frozen=True)
class ProfileConfig:
    name: str
    key_file: str
    providers: tuple[str, ...] = ("csv", "moomoo")
    benchmarks: tuple[str, ...] = ()
    schema_version: int = 1
    llm: LLMSettings = LLMSettings()
    dividends: DividendSettings = DividendSettings()
    reporting_currency: Currency = Currency.SGD
    drawdown: DrawdownSettings = DrawdownSettings()

    def __post_init__(self) -> None:
        validate_profile_name(self.name)
        if not Path(self.key_file).is_absolute():
            raise ProfileError("key_file must be absolute")
        try:
            from stonks_cli.plugins import validate_provider_configuration

            providers = validate_provider_configuration(self.providers)
        except ProviderError as error:
            raise ProfileError(str(error)) from error
        if not isinstance(self.reporting_currency, Currency):
            raise ProfileError("profile reporting currency is invalid")
        if not isinstance(self.drawdown, DrawdownSettings):
            raise ProfileError("profile drawdown settings are invalid")
        object.__setattr__(self, "providers", providers)


def profile_dir(name: str) -> Path:
    return app_root() / "profiles" / validate_profile_name(name)


def config_path(name: str) -> Path:
    return profile_dir(name) / "profile.json"


def save_profile(config: ProfileConfig) -> None:
    directory = profile_dir(config.name)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = config_path(config.name)
    data = asdict(config)
    if not config.llm.enabled:
        data.pop("llm")
    if config.dividends == DividendSettings():
        data.pop("dividends")
    if config.reporting_currency is Currency.SGD:
        data.pop("reporting_currency")
    if config.drawdown == DrawdownSettings():
        data.pop("drawdown")
    payload = json.dumps(data, sort_keys=True, indent=2).encode() + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)


def enable_provider(config: ProfileConfig, provider_id: str) -> ProfileConfig:
    providers = (*config.providers, provider_id)
    return ProfileConfig(
        config.name,
        config.key_file,
        providers,
        config.benchmarks,
        config.schema_version,
        config.llm,
        config.dividends,
        config.reporting_currency,
        config.drawdown,
    )


def disable_provider(config: ProfileConfig, provider_id: str) -> ProfileConfig:
    identifier = provider_id.strip().lower()
    providers = tuple(item for item in config.providers if item != identifier)
    if len(providers) == len(config.providers):
        raise ProfileError("provider is not enabled")
    return ProfileConfig(
        config.name,
        config.key_file,
        providers,
        config.benchmarks,
        config.schema_version,
        config.llm,
        config.dividends,
        config.reporting_currency,
        config.drawdown,
    )


def configure_drawdown(
    config: ProfileConfig, warning_threshold: str, response_policy: DrawdownResponsePolicy | str
) -> ProfileConfig:
    try:
        policy = DrawdownResponsePolicy(response_policy)
    except ValueError as error:
        raise ProfileError("drawdown response policy is invalid") from error
    candidate = DrawdownSettings(
        warning_threshold, policy, config.drawdown.version
    )
    if candidate == config.drawdown:
        return config
    return replace(config, drawdown=replace(candidate, version=config.drawdown.version + 1))


def load_profile(name: str) -> ProfileConfig:
    path = config_path(name)
    if not path.is_file():
        raise ProfileError("profile not found")
    try:
        value = json.loads(path.read_text())
        return ProfileConfig(
            name=value["name"],
            key_file=value["key_file"],
            providers=tuple(value.get("providers", ("csv", "moomoo"))),
            benchmarks=tuple(value.get("benchmarks", ())),
            schema_version=int(value.get("schema_version", 1)),
            llm=LLMSettings(**value.get("llm", {})),
            dividends=DividendSettings(**value.get("dividends", {})),
            reporting_currency=Currency(value.get("reporting_currency", Currency.SGD)),
            drawdown=DrawdownSettings(**value.get("drawdown", {})),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ProfileError("invalid profile") from error
