// SPDX-License-Identifier: MIT

//! Bounded OpenTelemetry boundary instrumentation.

/// Instrumented execution boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TelemetryBoundary {
    /// Core API operation.
    Core,
    /// Embedding-provider operation.
    Provider,
    /// Durable storage operation.
    Storage,
    /// HTTP transport operation.
    Http,
    /// Model Context Protocol transport operation.
    Mcp,
}

#[cfg(any(test, feature = "opentelemetry"))]
impl TelemetryBoundary {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Core => "core",
            Self::Provider => "provider",
            Self::Storage => "storage",
            Self::Http => "http",
            Self::Mcp => "mcp",
        }
    }
}

/// Bounded operation name accepted by instrumentation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TelemetryOperation {
    /// Core memory write.
    Write,
    /// Core memory recall.
    Recall,
    /// Provider embedding request.
    Embed,
    /// Durable embedded-memory write.
    StoreWrite,
    /// HTTP request lifecycle.
    Request,
    /// MCP message lifecycle.
    Message,
}

#[cfg(any(test, feature = "opentelemetry"))]
impl TelemetryOperation {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Write => "write",
            Self::Recall => "recall",
            Self::Embed => "embed",
            Self::StoreWrite => "store_write",
            Self::Request => "request",
            Self::Message => "message",
        }
    }
}

/// Bounded operation outcome.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TelemetryStatus {
    /// Operation completed successfully.
    Ok,
    /// Operation returned an error.
    Error,
}

#[cfg(any(test, feature = "opentelemetry"))]
impl TelemetryStatus {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Ok => "ok",
            Self::Error => "error",
        }
    }
}

/// Emits one content-safe OpenTelemetry span and counter measurement.
///
/// This is a no-op unless the crate is compiled with the `opentelemetry` feature.
pub fn record_boundary(
    boundary: TelemetryBoundary,
    operation: TelemetryOperation,
    status: TelemetryStatus,
) {
    #[cfg(feature = "opentelemetry")]
    emit(boundary, operation, status);

    #[cfg(not(feature = "opentelemetry"))]
    let _ = (boundary, operation, status);
}

#[cfg(feature = "opentelemetry")]
fn emit(boundary: TelemetryBoundary, operation: TelemetryOperation, status: TelemetryStatus) {
    use opentelemetry::trace::{Span, Tracer};
    use opentelemetry::{KeyValue, global};

    let attributes = [
        KeyValue::new("shibahama.component", boundary.as_str()),
        KeyValue::new("shibahama.operation", operation.as_str()),
        KeyValue::new("shibahama.status", status.as_str()),
    ];
    let mut span = global::tracer("shibahama").start(format!(
        "shibahama.{}.{}",
        boundary.as_str(),
        operation.as_str()
    ));

    span.set_attributes(attributes.clone());
    span.end();
    global::meter("shibahama")
        .u64_counter("shibahama.operation.count")
        .build()
        .add(1, &attributes);
}

#[cfg(test)]
mod tests {
    use super::{TelemetryBoundary, TelemetryOperation, TelemetryStatus, record_boundary};

    #[test]
    fn telemetry_dimensions_are_bounded_and_content_free() {
        for value in [
            TelemetryBoundary::Core.as_str(),
            TelemetryBoundary::Provider.as_str(),
            TelemetryBoundary::Storage.as_str(),
            TelemetryBoundary::Http.as_str(),
            TelemetryBoundary::Mcp.as_str(),
            TelemetryOperation::Write.as_str(),
            TelemetryOperation::Recall.as_str(),
            TelemetryOperation::Embed.as_str(),
            TelemetryOperation::StoreWrite.as_str(),
            TelemetryOperation::Request.as_str(),
            TelemetryOperation::Message.as_str(),
            TelemetryStatus::Ok.as_str(),
            TelemetryStatus::Error.as_str(),
        ] {
            assert!(
                value
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
            );
        }
    }

    #[test]
    fn boundary_recording_is_safe_when_no_provider_is_installed() {
        record_boundary(
            TelemetryBoundary::Core,
            TelemetryOperation::Write,
            TelemetryStatus::Ok,
        );
    }
}
