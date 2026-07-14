"""Isolated vNext decision-support package namespace."""

from stonks_cli.vnext.boundaries import PACKAGE_BOUNDARIES, PackageBoundary, VNextPackage, validate_package_boundaries
from stonks_cli.vnext.database import SQLiteConnectionFactory
from stonks_cli.vnext.errors import (
    VNextApplicationError,
    VNextConfigurationError,
    VNextExecutionDeniedError,
    VNextExternalDataError,
    VNextInvariantError,
)
from stonks_cli.vnext.events import (
    EVENT_SCHEMA_VERSION,
    EventSeverity,
    StructuredEvent,
    create_structured_event,
    deserialize_structured_event,
    serialize_structured_event,
)
from stonks_cli.vnext.filesystem import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    enforce_private_file,
    ensure_private_directory,
)
from stonks_cli.vnext.foundation import (
    RUN_IDENTITY_VERSION,
    Clock,
    FrozenUTCClock,
    RunIdentity,
    SecretReference,
    SystemUTCClock,
    UTCDateTime,
    as_utc,
    create_run_identity,
    load_run_identity,
    resolve_environment_secret,
    save_run_identity,
)
from stonks_cli.vnext.migrations import Migration, MigrationRegistry, MigrationRunner
from stonks_cli.vnext.runtime import RUNTIME_ROOT_ENV, RuntimeDirectories, RuntimeDirectory, runtime_directories

__all__ = [
    "Clock",
    "EventSeverity",
    "EVENT_SCHEMA_VERSION",
    "FrozenUTCClock",
    "PRIVATE_DIRECTORY_MODE",
    "PRIVATE_FILE_MODE",
    "Migration",
    "MigrationRegistry",
    "MigrationRunner",
    "PACKAGE_BOUNDARIES",
    "PackageBoundary",
    "RUN_IDENTITY_VERSION",
    "RUNTIME_ROOT_ENV",
    "RunIdentity",
    "SecretReference",
    "SQLiteConnectionFactory",
    "RuntimeDirectories",
    "RuntimeDirectory",
    "SystemUTCClock",
    "StructuredEvent",
    "UTCDateTime",
    "VNextApplicationError",
    "VNextConfigurationError",
    "VNextExecutionDeniedError",
    "VNextExternalDataError",
    "VNextInvariantError",
    "VNextPackage",
    "as_utc",
    "create_run_identity",
    "create_structured_event",
    "deserialize_structured_event",
    "enforce_private_file",
    "ensure_private_directory",
    "load_run_identity",
    "resolve_environment_secret",
    "save_run_identity",
    "serialize_structured_event",
    "runtime_directories",
    "validate_package_boundaries",
]
