from __future__ import annotations

import re
from dataclasses import dataclass

_EVENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")


@dataclass(frozen=True)
class AlertSubscription:
    subscription_id: str
    chat_id: str
    event_types: frozenset[str]
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.subscription_id, str) or not self.subscription_id:
            raise ValueError("alert subscription ID is invalid")
        if not isinstance(self.chat_id, str) or not self.chat_id:
            raise ValueError("alert subscription chat ID is invalid")
        if not isinstance(self.event_types, frozenset) or not self.event_types or not all(
            isinstance(event_type, str) and _EVENT_TYPE_PATTERN.fullmatch(event_type) for event_type in self.event_types
        ):
            raise ValueError("alert subscription event types are invalid")
        if not isinstance(self.enabled, bool):
            raise ValueError("alert subscription enabled state is invalid")
