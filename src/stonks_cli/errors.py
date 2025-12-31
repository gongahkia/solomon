from __future__ import annotations

from dataclasses import dataclass


class ExitCodes:
    OK = 0
    UNKNOWN_ERROR = 1
    USAGE_ERROR = 2
    BAD_CONFIG = 10
    NO_DATA = 11
    PROVIDER_ERROR = 12
    LLM_ERROR = 13


@dataclass(frozen=True)
class StonksError(Exception):
    message: str
    code: int = ExitCodes.UNKNOWN_ERROR

    def __str__(self) -> str:  # pragma: no cover
        return self.message


class BadConfigError(StonksError):
    def __init__(self, message: str = "Bad configuration"):
        super().__init__(message=message, code=ExitCodes.BAD_CONFIG)


class NoDataError(StonksError):
    def __init__(self, message: str = "No data available"):
        super().__init__(message=message, code=ExitCodes.NO_DATA)


class ProviderError(StonksError):
    def __init__(self, message: str = "Data provider error"):
        super().__init__(message=message, code=ExitCodes.PROVIDER_ERROR)


class LLMError(StonksError):
    def __init__(self, message: str = "LLM backend error"):
        super().__init__(message=message, code=ExitCodes.LLM_ERROR)
