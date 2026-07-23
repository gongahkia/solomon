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
_BENCHMARK_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9]{1,9}:[A-Z0-9][A-Z0-9._-]{0,31}$")
_LLM_PROVIDERS = frozenset(("ollama", "openai", "anthropic", "gemini"))
_BUDGET_PERIODS = frozenset(("none", "daily", "monthly"))
_BENCHMARK_RETURN_BASES = frozenset(("price_return", "total_return"))


def canonical_benchmark_identifier(identifier: str) -> str:
    value = identifier.strip().upper() if isinstance(identifier, str) else ""
    if not _BENCHMARK_IDENTIFIER.fullmatch(value):
        raise ProfileError("benchmark identifier must be canonical MARKET:SYMBOL")
    return value


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
class JournalSettings:
    open_on_advisory: bool = True
    retention_days: int | None = None
    display_reasons: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.open_on_advisory, bool) or not isinstance(self.display_reasons, bool):
            raise ProfileError("journal settings flags must be boolean")
        if self.retention_days is not None and (
            not isinstance(self.retention_days, int)
            or isinstance(self.retention_days, bool)
            or not 1 <= self.retention_days <= 36_500
        ):
            raise ProfileError("journal retention days must be between 1 and 36500")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("journal settings version must be a positive integer")


@dataclass(frozen=True)
class BenchmarkComponent:
    identifier: str
    name: str
    currency: Currency
    weight: str
    source_url: str
    return_basis: str = "total_return"

    def __post_init__(self) -> None:
        identifier = canonical_benchmark_identifier(self.identifier)
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > 256:
            raise ProfileError("benchmark name is invalid")
        if not isinstance(self.currency, Currency):
            raise ProfileError("benchmark currency is invalid")
        if not isinstance(self.weight, str) or not self.weight.strip():
            raise ProfileError("benchmark weight must be decimal")
        try:
            weight = Decimal(self.weight)
        except InvalidOperation as error:
            raise ProfileError("benchmark weight must be decimal") from error
        if not weight.is_finite() or not Decimal("0") < weight <= Decimal("1"):
            raise ProfileError("benchmark weight must be between zero and one")
        if not isinstance(self.source_url, str):
            raise ProfileError("benchmark source URL is invalid")
        source_url = self.source_url.strip()
        parsed = urlsplit(source_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProfileError("benchmark source URL must be an HTTPS URL without credentials")
        return_basis = self.return_basis.strip().lower() if isinstance(self.return_basis, str) else ""
        if return_basis not in _BENCHMARK_RETURN_BASES:
            raise ProfileError("benchmark return basis is invalid")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "weight", format(weight, "f"))
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "return_basis", return_basis)

    @property
    def decimal_weight(self) -> Decimal:
        return Decimal(self.weight)


_DEFAULT_BENCHMARK_COMPONENTS = (
    BenchmarkComponent(
        "US:SPX",
        "S&P 500 Index",
        Currency.USD,
        "0.75",
        "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
    ),
    BenchmarkComponent(
        "SG:STI",
        "Straits Times Index",
        Currency.SGD,
        "0.25",
        "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/straits-times-index-ground-rules.pdf",
    ),
)


@dataclass(frozen=True)
class BenchmarkSettings:
    components: tuple[BenchmarkComponent, ...] = _DEFAULT_BENCHMARK_COMPONENTS
    version: int = 1

    def __post_init__(self) -> None:
        if not self.components or not all(isinstance(item, BenchmarkComponent) for item in self.components):
            raise ProfileError("benchmark components are required")
        identifiers = tuple(item.identifier for item in self.components)
        if len(set(identifiers)) != len(identifiers):
            raise ProfileError("benchmark components must be unique")
        if sum((item.decimal_weight for item in self.components), Decimal("0")) != Decimal("1"):
            raise ProfileError("benchmark component weights must total one")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("benchmark settings version must be a positive integer")


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
    journal: JournalSettings = JournalSettings()
    benchmark: BenchmarkSettings = BenchmarkSettings()

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
        if not isinstance(self.benchmark, BenchmarkSettings):
            raise ProfileError("profile benchmark settings are invalid")
        if not isinstance(self.drawdown, DrawdownSettings):
            raise ProfileError("profile drawdown settings are invalid")
        if not isinstance(self.journal, JournalSettings):
            raise ProfileError("profile journal settings are invalid")
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
    data["benchmark"] = {
        "components": [
            {
                "identifier": component.identifier,
                "name": component.name,
                "currency": component.currency.value,
                "weight": component.weight,
                "source_url": component.source_url,
                "return_basis": component.return_basis,
            }
            for component in config.benchmark.components
        ],
        "version": config.benchmark.version,
    }
    if config.drawdown == DrawdownSettings():
        data.pop("drawdown")
    if config.journal == JournalSettings():
        data.pop("journal")
    payload = json.dumps(data, sort_keys=True, indent=2).encode() + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)


def enable_provider(config: ProfileConfig, provider_id: str) -> ProfileConfig:
    providers = (*config.providers, provider_id)
    return replace(config, providers=providers)


def disable_provider(config: ProfileConfig, provider_id: str) -> ProfileConfig:
    identifier = provider_id.strip().lower()
    providers = tuple(item for item in config.providers if item != identifier)
    if len(providers) == len(config.providers):
        raise ProfileError("provider is not enabled")
    return replace(config, providers=providers)


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


def configure_benchmark(
    config: ProfileConfig, components: tuple[BenchmarkComponent, ...]
) -> ProfileConfig:
    candidate = BenchmarkSettings(components, config.benchmark.version)
    if candidate == config.benchmark:
        return config
    return replace(config, benchmark=replace(candidate, version=config.benchmark.version + 1))


def configure_journal(
    config: ProfileConfig,
    *,
    open_on_advisory: bool,
    retention_days: int | None,
    display_reasons: bool,
) -> ProfileConfig:
    candidate = JournalSettings(
        open_on_advisory,
        retention_days,
        display_reasons,
        config.journal.version,
    )
    if candidate == config.journal:
        return config
    return replace(config, journal=replace(candidate, version=config.journal.version + 1))


def benchmark_settings_from_data(value: object) -> BenchmarkSettings:
    if value is None:
        return BenchmarkSettings()
    if not isinstance(value, dict):
        raise TypeError("benchmark must be an object")
    if "components" not in value:
        return BenchmarkSettings()
    component_values = value["components"]
    if not isinstance(component_values, list):
        raise TypeError("benchmark components must be a list")
    return BenchmarkSettings(
        tuple(
            BenchmarkComponent(
                identifier=item["identifier"],
                name=item["name"],
                currency=Currency(item["currency"]),
                weight=item["weight"],
                source_url=item["source_url"],
                return_basis=item.get("return_basis", "total_return"),
            )
            for item in component_values
        ),
        int(value.get("version", 1)),
    )


def load_profile(name: str) -> ProfileConfig:
    path = config_path(name)
    if not path.is_file():
        raise ProfileError("profile not found")
    try:
        value = json.loads(path.read_text())
        benchmark = benchmark_settings_from_data(value.get("benchmark"))
        return ProfileConfig(
            name=value["name"],
            key_file=value["key_file"],
            providers=tuple(value.get("providers", ("csv", "moomoo"))),
            benchmarks=tuple(value.get("benchmarks", ())),
            benchmark=benchmark,
            schema_version=int(value.get("schema_version", 1)),
            llm=LLMSettings(**value.get("llm", {})),
            dividends=DividendSettings(**value.get("dividends", {})),
            reporting_currency=Currency(value.get("reporting_currency", Currency.SGD)),
            drawdown=DrawdownSettings(**value.get("drawdown", {})),
            journal=JournalSettings(**value.get("journal", {})),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ProfileError("invalid profile") from error
