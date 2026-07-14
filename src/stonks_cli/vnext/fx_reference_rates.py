from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.foundation import as_utc

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")
_PROVIDER_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")


@dataclass(frozen=True)
class FXReferenceRate:
    base_currency: str
    quote_currency: str
    quote_amount_per_base: float
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.base_currency, str) or not _CURRENCY_PATTERN.fullmatch(self.base_currency):
            raise ValueError("FX reference base currency is invalid")
        if not isinstance(self.quote_currency, str) or not _CURRENCY_PATTERN.fullmatch(self.quote_currency):
            raise ValueError("FX reference quote currency is invalid")
        if self.base_currency == self.quote_currency:
            raise ValueError("FX reference currencies must differ")
        if not isinstance(self.quote_amount_per_base, float) or not math.isfinite(self.quote_amount_per_base) or self.quote_amount_per_base <= 0:
            raise ValueError("FX reference rate is invalid")
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


@dataclass(frozen=True)
class FXReferenceRateBatch:
    provider_id: str
    quote_currency: str
    rates: tuple[FXReferenceRate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not _PROVIDER_ID_PATTERN.fullmatch(self.provider_id):
            raise ValueError("FX reference provider ID is invalid")
        if not isinstance(self.quote_currency, str) or not _CURRENCY_PATTERN.fullmatch(self.quote_currency):
            raise ValueError("FX reference quote currency is invalid")
        if not isinstance(self.rates, tuple) or not self.rates or not all(isinstance(rate, FXReferenceRate) for rate in self.rates):
            raise ValueError("FX reference rates are invalid")
        if any(rate.quote_currency != self.quote_currency for rate in self.rates):
            raise ValueError("FX reference rates use a different quote currency")
        base_currencies = tuple(rate.base_currency for rate in self.rates)
        if len(set(base_currencies)) != len(base_currencies):
            raise ValueError("FX reference base currencies must be unique")
        if base_currencies != tuple(sorted(base_currencies)):
            raise ValueError("FX reference rates are not canonical")


@runtime_checkable
class FXReferenceRateProvider(Protocol):
    provider_id: str

    def list_fx_reference_rates(self, base_currencies: Sequence[str], quote_currency: str) -> Sequence[FXReferenceRate]: ...


def ingest_fx_reference_rates(
    provider: FXReferenceRateProvider, base_currencies: Sequence[str], quote_currency: str
) -> FXReferenceRateBatch:
    if not isinstance(base_currencies, Sequence) or isinstance(base_currencies, (str, bytes)) or not base_currencies:
        raise ValueError("FX reference base currencies are invalid")
    if not all(isinstance(currency, str) and _CURRENCY_PATTERN.fullmatch(currency) for currency in base_currencies):
        raise ValueError("FX reference base currencies are invalid")
    if len(set(base_currencies)) != len(base_currencies):
        raise ValueError("FX reference base currencies must be unique")
    if not isinstance(quote_currency, str) or not _CURRENCY_PATTERN.fullmatch(quote_currency) or quote_currency in base_currencies:
        raise ValueError("FX reference quote currency is invalid")
    provider_id = getattr(provider, "provider_id", None)
    getter = getattr(provider, "list_fx_reference_rates", None)
    if not isinstance(provider_id, str) or not callable(getter):
        raise VNextExternalDataError("FX reference provider is incompatible")
    try:
        rates = getter(tuple(sorted(base_currencies)), quote_currency)
    except VNextExternalDataError:
        raise
    except Exception as error:
        raise VNextExternalDataError("FX reference provider is unavailable") from error
    if not isinstance(rates, Sequence) or isinstance(rates, (str, bytes)):
        raise VNextExternalDataError("FX reference provider response is malformed")
    try:
        batch = FXReferenceRateBatch(provider_id, quote_currency, tuple(rates))
    except (TypeError, ValueError) as error:
        raise VNextExternalDataError("FX reference provider response is malformed") from error
    if {rate.base_currency for rate in batch.rates} != set(base_currencies):
        raise VNextExternalDataError("FX reference provider response is incomplete")
    return batch
