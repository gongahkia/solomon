# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    STATE = "state"
    UPSTREAM = "upstream"
    INTERNAL = "internal"


class SolomonError(RuntimeError):
    status_code = 500
    code = "solomon_error"
    category = ErrorCategory.INTERNAL
    retryable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def error_payload(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class NotFoundError(SolomonError):
    status_code = 404
    code = "not_found"
    category = ErrorCategory.STATE


class PolicyRefusalError(SolomonError):
    status_code = 403
    code = "policy_refusal"
    category = ErrorCategory.AUTHORIZATION


class BadRequestError(SolomonError):
    status_code = 422
    code = "bad_request"
    category = ErrorCategory.VALIDATION


class ConflictError(SolomonError):
    status_code = 409
    code = "conflict"
    category = ErrorCategory.STATE


class UpstreamError(SolomonError):
    status_code = 503
    code = "upstream_failure"
    category = ErrorCategory.UPSTREAM
    retryable = True


def domain_error_from_exception(error: Exception) -> SolomonError:
    if isinstance(error, SolomonError):
        return error
    if isinstance(error, (ConnectionError, OSError, TimeoutError)):
        return UpstreamError("upstream dependency failed")
    if isinstance(error, KeyError):
        return NotFoundError("requested state was not found")
    if isinstance(error, ValueError):
        return BadRequestError("request validation failed")
    return SolomonError("internal request failure")


__all__ = [
    "BadRequestError",
    "ConflictError",
    "ErrorCategory",
    "NotFoundError",
    "PolicyRefusalError",
    "SolomonError",
    "UpstreamError",
    "domain_error_from_exception",
]
