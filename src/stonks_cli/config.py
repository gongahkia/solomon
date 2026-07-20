from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_data_path

from stonks_cli.errors import ProfileError

_PROFILE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


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

    def __post_init__(self) -> None:
        validate_profile_name(self.name)
        if not Path(self.key_file).is_absolute():
            raise ProfileError("key_file must be absolute")


def profile_dir(name: str) -> Path:
    return app_root() / "profiles" / validate_profile_name(name)


def config_path(name: str) -> Path:
    return profile_dir(name) / "profile.json"


def save_profile(config: ProfileConfig) -> None:
    directory = profile_dir(config.name)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = config_path(config.name)
    payload = json.dumps(asdict(config), sort_keys=True, indent=2).encode() + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)


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
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ProfileError("invalid profile") from error
