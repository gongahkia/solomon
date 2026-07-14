from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.source_citations import SourceCitation


@dataclass(frozen=True)
class CitationVerification:
    citation: SourceCitation
    verified_at: datetime
    maximum_age: timedelta
    age: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.citation, SourceCitation):
            raise TypeError("citation verification requires a source citation")
        object.__setattr__(self, "citation", SourceCitation.from_data(self.citation.to_data()))
        object.__setattr__(self, "verified_at", as_utc(self.verified_at))
        if not isinstance(self.maximum_age, timedelta) or self.maximum_age <= timedelta(0):
            raise ValueError("citation verification maximum age is invalid")
        expected_age = self.verified_at - self.citation.retrieved_at
        if expected_age < timedelta(0):
            raise ValueError("citation verification cannot use a future timestamp")
        if expected_age > self.maximum_age:
            raise ValueError("citation verification timestamp is stale")
        if not isinstance(self.age, timedelta) or self.age != expected_age:
            raise ValueError("citation verification age is inconsistent")


def verify_source_citation(citation: SourceCitation, evaluated_at: datetime, maximum_age: timedelta) -> CitationVerification:
    if not isinstance(citation, SourceCitation):
        raise TypeError("citation verification requires a source citation")
    evaluation_time = as_utc(evaluated_at)
    return CitationVerification(citation, evaluation_time, maximum_age, evaluation_time - citation.retrieved_at)
