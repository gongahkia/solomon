// SPDX-License-Identifier: MIT

//! Bounded OpenTelemetry boundary instrumentation.

use crate::observability::{ObservabilityOperation, ObservabilityRecord};
use std::sync::{Arc, OnceLock, RwLock};

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

/// Normalized record supplied to an optional vendor telemetry exporter.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NormalizedTelemetry {
    /// Bounded component category.
    pub boundary: TelemetryBoundary,
    /// Bounded operation category.
    pub operation: TelemetryOperation,
    /// Success or error only.
    pub status: TelemetryStatus,
    /// Whole-millisecond duration.
    pub duration_ms: u64,
    /// Accepted or returned item count.
    pub item_count: usize,
}

/// Optional vendor-specific telemetry sink.
pub trait TelemetryExporter: Send + Sync {
    /// Exports one normalized record without receiving memory, scope, or identity data.
    ///
    /// # Errors
    ///
    /// Returns an exporter-specific failure; Shibahama ignores it.
    fn export(
        &self,
        record: NormalizedTelemetry,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>>;
}

static TELEMETRY_EXPORTER: OnceLock<RwLock<Option<Arc<dyn TelemetryExporter>>>> = OnceLock::new();

/// Installs or removes the process-wide best-effort telemetry exporter.
pub fn set_telemetry_exporter(exporter: Option<Arc<dyn TelemetryExporter>>) {
    let registry = TELEMETRY_EXPORTER.get_or_init(|| RwLock::new(None));
    if let Ok(mut current) = registry.write() {
        *current = exporter;
    }
}

/// Exports a normalized durable record and ignores exporter failures.
pub fn export_observability(record: &ObservabilityRecord) {
    let Some(exporter) = TELEMETRY_EXPORTER
        .get()
        .and_then(|registry| registry.read().ok().and_then(|current| current.clone()))
    else {
        return;
    };
    let operation = match record.operation {
        ObservabilityOperation::ProviderCapture | ObservabilityOperation::AutomaticCapture => {
            TelemetryOperation::Write
        }
        ObservabilityOperation::ProviderRecall | ObservabilityOperation::AutomaticContext => {
            TelemetryOperation::Recall
        }
    };
    let _ = exporter.export(NormalizedTelemetry {
        boundary: TelemetryBoundary::Provider,
        operation,
        status: if record.error_code.is_some() {
            TelemetryStatus::Error
        } else {
            TelemetryStatus::Ok
        },
        duration_ms: record.duration_ms,
        item_count: record.item_count,
    });
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
    use super::{
        NormalizedTelemetry, TelemetryBoundary, TelemetryExporter, TelemetryOperation,
        TelemetryStatus, export_observability, record_boundary, set_telemetry_exporter,
    };
    use crate::observability::{ObservabilityOperation, ObservabilityRecord};
    use std::sync::{Arc, Mutex};

    struct FakeExporter {
        records: Mutex<Vec<NormalizedTelemetry>>,
        fail: bool,
    }

    impl TelemetryExporter for FakeExporter {
        fn export(
            &self,
            record: NormalizedTelemetry,
        ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
            self.records
                .lock()
                .expect("fake exporter lock")
                .push(record);
            if self.fail {
                return Err(Box::new(std::io::Error::other("expected failure")));
            }
            Ok(())
        }
    }

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

    #[test]
    fn fake_exporter_receives_only_normalized_records_and_failures_are_ignored() {
        let exporter = Arc::new(FakeExporter {
            records: Mutex::new(Vec::new()),
            fail: false,
        });
        set_telemetry_exporter(Some(exporter.clone()));
        export_observability(&ObservabilityRecord {
            operation: ObservabilityOperation::ProviderCapture,
            duration_ms: 9,
            item_count: 2,
            provider: Some("vendor-private".to_owned()),
            model: Some("model-private".to_owned()),
            policy_outcome: None,
            error_code: None,
            scope: Some(crate::model::MemoryScope::default()),
        });
        assert_eq!(
            exporter
                .records
                .lock()
                .expect("fake exporter lock")
                .as_slice(),
            &[NormalizedTelemetry {
                boundary: TelemetryBoundary::Provider,
                operation: TelemetryOperation::Write,
                status: TelemetryStatus::Ok,
                duration_ms: 9,
                item_count: 2
            }]
        );
        set_telemetry_exporter(Some(Arc::new(FakeExporter {
            records: Mutex::new(Vec::new()),
            fail: true,
        })));
        export_observability(&ObservabilityRecord::failure(
            ObservabilityOperation::ProviderRecall,
            1,
            None,
            None,
            "SHIBA_PROVIDER",
            None,
        ));
        set_telemetry_exporter(None);
    }
}
