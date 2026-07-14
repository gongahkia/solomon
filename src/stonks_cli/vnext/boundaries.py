from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class VNextPackage(StrEnum):
    FOUNDATION = "foundation"
    BROKER = "broker"
    RESEARCH = "research"
    PORTFOLIO = "portfolio"
    OPERATOR = "operator"
    RELIABILITY = "reliability"
    EXECUTION = "execution"


class BrokerAccess(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"


@dataclass(frozen=True)
class PackageBoundary:
    package: VNextPackage
    dependencies: frozenset[VNextPackage]
    broker_access: BrokerAccess = BrokerAccess.NONE
    allows_order_submission: bool = False


PACKAGE_BOUNDARIES: Mapping[VNextPackage, PackageBoundary] = {
    VNextPackage.FOUNDATION: PackageBoundary(VNextPackage.FOUNDATION, frozenset()),
    VNextPackage.BROKER: PackageBoundary(VNextPackage.BROKER, frozenset({VNextPackage.FOUNDATION}), BrokerAccess.READ_ONLY),
    VNextPackage.RESEARCH: PackageBoundary(VNextPackage.RESEARCH, frozenset({VNextPackage.FOUNDATION, VNextPackage.BROKER})),
    VNextPackage.PORTFOLIO: PackageBoundary(VNextPackage.PORTFOLIO, frozenset({VNextPackage.FOUNDATION, VNextPackage.BROKER})),
    VNextPackage.OPERATOR: PackageBoundary(
        VNextPackage.OPERATOR, frozenset({VNextPackage.FOUNDATION, VNextPackage.PORTFOLIO, VNextPackage.RESEARCH})
    ),
    VNextPackage.RELIABILITY: PackageBoundary(VNextPackage.RELIABILITY, frozenset({VNextPackage.FOUNDATION})),
    VNextPackage.EXECUTION: PackageBoundary(
        VNextPackage.EXECUTION,
        frozenset({VNextPackage.FOUNDATION, VNextPackage.OPERATOR, VNextPackage.PORTFOLIO, VNextPackage.RELIABILITY}),
    ),
}


def validate_package_boundaries(boundaries: Mapping[VNextPackage, PackageBoundary]) -> None:
    expected = set(VNextPackage)
    actual = set(boundaries)
    if actual != expected:
        raise ValueError(f"package boundary coverage mismatch: missing={sorted(expected - actual)} extra={sorted(actual - expected)}")
    for package, boundary in boundaries.items():
        if boundary.package != package:
            raise ValueError(f"boundary key does not match package:{package}")
        if package in boundary.dependencies:
            raise ValueError(f"package cannot depend on itself:{package}")
        unknown_dependencies = boundary.dependencies - expected
        if unknown_dependencies:
            raise ValueError(f"unknown package dependencies:{sorted(unknown_dependencies)}")
        if package != VNextPackage.BROKER and boundary.broker_access != BrokerAccess.NONE:
            raise ValueError(f"only broker package may access broker data:{package}")
        if package == VNextPackage.BROKER and boundary.broker_access != BrokerAccess.READ_ONLY:
            raise ValueError("broker package must be read-only")
        if boundary.allows_order_submission:
            raise ValueError(f"order submission is prohibited:{package}")
        if package != VNextPackage.EXECUTION and VNextPackage.EXECUTION in boundary.dependencies:
            raise ValueError(f"non-execution package cannot depend on execution:{package}")
    _assert_acyclic(boundaries)


def _assert_acyclic(boundaries: Mapping[VNextPackage, PackageBoundary]) -> None:
    visiting: set[VNextPackage] = set()
    visited: set[VNextPackage] = set()

    def visit(package: VNextPackage) -> None:
        if package in visiting:
            raise ValueError(f"cyclic package dependencies:{package}")
        if package in visited:
            return
        visiting.add(package)
        for dependency in boundaries[package].dependencies:
            visit(dependency)
        visiting.remove(package)
        visited.add(package)

    for package in boundaries:
        visit(package)
