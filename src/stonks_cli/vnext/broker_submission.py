from __future__ import annotations

import re

from stonks_cli.vnext.errors import VNextExecutionDeniedError

_BROKER_METHOD_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
BLOCKED_BROKER_SUBMISSION_METHODS = frozenset(
    {
        "cancel_order",
        "change_order",
        "modify_order",
        "place_order",
        "replace_order",
        "submit_order",
        "unlock_trade",
    }
)
BLOCKED_BROKER_MUTATION_METHODS = BLOCKED_BROKER_SUBMISSION_METHODS | frozenset(
    {"subscribe", "unsubscribe", "unsubscribe_all"}
)


def require_read_only_broker_method(method: object) -> str:
    if not isinstance(method, str) or not _BROKER_METHOD_PATTERN.fullmatch(method):
        raise ValueError("broker method name is invalid")
    if method in BLOCKED_BROKER_MUTATION_METHODS:
        raise VNextExecutionDeniedError(f"broker method is prohibited:{method}")
    return method
