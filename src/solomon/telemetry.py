# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


class SolomonTelemetry:
    def __init__(
        self,
        *,
        enabled: bool = False,
        service_name: str = "solomon",
        otlp_endpoint: str | None = None,
        span_exporter: SpanExporter | None = None,
    ) -> None:
        if otlp_endpoint is not None:
            _validate_otlp_endpoint(otlp_endpoint)
        self.enabled = enabled or span_exporter is not None
        self.provider: TracerProvider | None = None
        if not self.enabled:
            self.tracer = trace.get_tracer("solomon")
            return
        self.provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
        if span_exporter is not None:
            self.provider.add_span_processor(BatchSpanProcessor(span_exporter))
        elif otlp_endpoint is not None:
            self.provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        self.tracer = self.provider.get_tracer("solomon")

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, str | int | float | bool] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[Span | None]:
        if not self.enabled:
            yield None
            return
        context = TraceContextTextMapPropagator().extract(carrier=headers) if headers is not None else None
        with self.tracer.start_as_current_span(name, context=context) as span:
            for key, value in (attributes or {}).items():
                span.set_attribute(key, value)
            try:
                yield span
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, exc.__class__.__name__))
                raise

    def force_flush(self) -> bool:
        return self.provider.force_flush() if self.provider is not None else True

    def shutdown(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()


def telemetry_from_settings(
    *,
    enabled: bool,
    service_name: str,
    otlp_endpoint: str | None,
) -> SolomonTelemetry:
    return SolomonTelemetry(enabled=enabled, service_name=service_name, otlp_endpoint=otlp_endpoint)


def _validate_otlp_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("OpenTelemetry endpoint must be an absolute HTTP(S) URL without query or fragment")
