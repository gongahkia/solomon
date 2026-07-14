from __future__ import annotations

from dataclasses import replace

import pytest

from stonks_cli.vnext.boundaries import BrokerAccess, PACKAGE_BOUNDARIES, PackageBoundary, VNextPackage, validate_package_boundaries


def test_default_vnext_boundaries_are_complete_and_valid():
    validate_package_boundaries(PACKAGE_BOUNDARIES)
    assert set(PACKAGE_BOUNDARIES) == set(VNextPackage)
    assert PACKAGE_BOUNDARIES[VNextPackage.BROKER].broker_access is BrokerAccess.READ_ONLY
    assert all(not boundary.allows_order_submission for boundary in PACKAGE_BOUNDARIES.values())


@pytest.mark.parametrize(
    ("package", "boundary", "message"),
    [
        (VNextPackage.BROKER, replace(PACKAGE_BOUNDARIES[VNextPackage.BROKER], broker_access=BrokerAccess.NONE), "broker package must be read-only"),
        (VNextPackage.RESEARCH, replace(PACKAGE_BOUNDARIES[VNextPackage.RESEARCH], broker_access=BrokerAccess.READ_ONLY), "only broker package may access broker data"),
        (VNextPackage.EXECUTION, replace(PACKAGE_BOUNDARIES[VNextPackage.EXECUTION], allows_order_submission=True), "order submission is prohibited"),
        (VNextPackage.FOUNDATION, replace(PACKAGE_BOUNDARIES[VNextPackage.FOUNDATION], dependencies=frozenset({VNextPackage.FOUNDATION})), "package cannot depend on itself"),
    ],
)
def test_invalid_vnext_boundaries_fail_closed(package, boundary, message):
    boundaries = dict(PACKAGE_BOUNDARIES)
    boundaries[package] = boundary

    with pytest.raises(ValueError, match=message):
        validate_package_boundaries(boundaries)


def test_missing_vnext_boundary_fails_closed():
    boundaries = dict(PACKAGE_BOUNDARIES)
    boundaries.pop(VNextPackage.RELIABILITY)

    with pytest.raises(ValueError, match="package boundary coverage mismatch"):
        validate_package_boundaries(boundaries)


def test_cyclic_vnext_boundaries_fail_closed():
    boundaries = dict(PACKAGE_BOUNDARIES)
    boundaries[VNextPackage.RESEARCH] = PackageBoundary(
        VNextPackage.RESEARCH,
        frozenset({VNextPackage.FOUNDATION, VNextPackage.BROKER, VNextPackage.PORTFOLIO}),
    )
    boundaries[VNextPackage.PORTFOLIO] = PackageBoundary(
        VNextPackage.PORTFOLIO,
        frozenset({VNextPackage.FOUNDATION, VNextPackage.BROKER, VNextPackage.RESEARCH}),
    )

    with pytest.raises(ValueError, match="cyclic package dependencies"):
        validate_package_boundaries(boundaries)
