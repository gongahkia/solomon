from __future__ import annotations

import pytest

from stonks_cli.vnext.health import HealthStatus
from stonks_cli.vnext.moomoo import MoomooOpenDProcessContract, OpenDEndpointProbe, OpenDEndpointStatus
from stonks_cli.vnext.opend_availability import OPEND_AVAILABILITY_HEALTH_CHECK, monitor_opend_availability


def test_opend_availability_monitor_maps_read_only_probe_outcomes_to_health():
    contract = MoomooOpenDProcessContract("127.0.0.1", 11111)

    available = monitor_opend_availability(contract, probe=lambda *_args, **_kwargs: OpenDEndpointProbe(OpenDEndpointStatus.AVAILABLE, "available", 1.0))
    unavailable = monitor_opend_availability(contract, probe=lambda *_args, **_kwargs: OpenDEndpointProbe(OpenDEndpointStatus.UNAVAILABLE, "connection_unavailable", None))

    assert available.status is HealthStatus.PASS
    assert unavailable.status is HealthStatus.FAIL
    assert available.name == OPEND_AVAILABILITY_HEALTH_CHECK


@pytest.mark.parametrize("contract,probe", [(None, lambda *_args, **_kwargs: None), (MoomooOpenDProcessContract("127.0.0.1", 11111), None)])
def test_opend_availability_monitor_fails_closed_for_missing_or_malformed_external_data(contract, probe):
    with pytest.raises(TypeError, match="OpenD availability monitor"):
        monitor_opend_availability(contract, probe=probe)  # type: ignore[arg-type]
