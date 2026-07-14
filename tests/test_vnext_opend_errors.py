import pytest

from stonks_cli.vnext.errors import (
    OpenDContextIncompatibleError,
    OpenDEndpointUnavailableError,
    OpenDError,
    OpenDQuotaExceededError,
    OpenDResponseMalformedError,
    VNextExternalDataError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "message"),
    [
        (OpenDEndpointUnavailableError, "vnext.opend.endpoint_unavailable", "OpenD endpoint is unavailable."),
        (OpenDContextIncompatibleError, "vnext.opend.context_incompatible", "OpenD context is incompatible."),
        (OpenDQuotaExceededError, "vnext.opend.quota_exceeded", "OpenD request quota is unavailable."),
        (OpenDResponseMalformedError, "vnext.opend.response_malformed", "OpenD response is malformed."),
    ],
)
def test_typed_opend_errors_are_safe_external_data_errors(error_type, code, message):
    error = error_type("sensitive broker payload")

    assert isinstance(error, (OpenDError, VNextExternalDataError))
    assert error.to_data() == {"error": {"code": code, "message": message}}
