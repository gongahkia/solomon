from __future__ import annotations

from typing import ClassVar

from stonks_cli.errors import ExitCodes, StonksError


class VNextApplicationError(StonksError):
    public_code: ClassVar[str] = "vnext.application_error"
    public_message: ClassVar[str] = "vNext application error."
    exit_code: ClassVar[int] = ExitCodes.UNKNOWN_ERROR

    def __init__(self, internal_message: str | None = None) -> None:
        super().__init__(message=internal_message or self.public_message, code=self.exit_code)

    def to_data(self) -> dict[str, object]:
        return {"error": {"code": self.public_code, "message": self.public_message}}


class VNextConfigurationError(VNextApplicationError):
    public_code = "vnext.configuration.invalid"
    public_message = "Invalid vNext configuration."
    exit_code = ExitCodes.BAD_CONFIG


class VNextExternalDataError(VNextApplicationError):
    public_code = "vnext.external_data.unavailable"
    public_message = "Required external data is unavailable."
    exit_code = ExitCodes.PROVIDER_ERROR


class VNextInvariantError(VNextApplicationError):
    public_code = "vnext.invariant.failed"
    public_message = "A vNext safety invariant failed."


class VNextExecutionDeniedError(VNextApplicationError):
    public_code = "vnext.execution.denied"
    public_message = "vNext execution is disabled."
    exit_code = ExitCodes.USAGE_ERROR
