"""Isolated vNext decision-support package namespace."""

from stonks_cli.vnext.boundaries import PACKAGE_BOUNDARIES, PackageBoundary, VNextPackage, validate_package_boundaries
from stonks_cli.vnext.foundation import (
    RUN_IDENTITY_VERSION,
    Clock,
    FrozenUTCClock,
    RunIdentity,
    SystemUTCClock,
    UTCDateTime,
    as_utc,
    create_run_identity,
    load_run_identity,
    save_run_identity,
)

__all__ = [
    "Clock",
    "FrozenUTCClock",
    "PACKAGE_BOUNDARIES",
    "PackageBoundary",
    "RUN_IDENTITY_VERSION",
    "RunIdentity",
    "SystemUTCClock",
    "UTCDateTime",
    "VNextPackage",
    "as_utc",
    "create_run_identity",
    "load_run_identity",
    "save_run_identity",
    "validate_package_boundaries",
]
