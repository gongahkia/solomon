# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


class SolomonError(RuntimeError):
    status_code = 500
    code = "solomon_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(SolomonError):
    status_code = 404
    code = "not_found"


class PolicyRefusalError(SolomonError):
    status_code = 403
    code = "policy_refusal"


class BadRequestError(SolomonError):
    status_code = 422
    code = "bad_request"

