// SPDX-License-Identifier: MIT

//! Content-free operational records for capture and retrieval.

use crate::model::MemoryScope;
use crate::policy::PolicyAuditDisposition;
use serde::{Deserialize, Serialize};

/// Operation measured without recording memory, query, vector, source-reference, or secret data.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservabilityOperation {
    /// Provider-backed memory capture.
    ProviderCapture,
    /// Provider-backed retrieval.
    ProviderRecall,
    /// Policy-authorized automatic capture.
    AutomaticCapture,
    /// Policy-authorized automatic context assembly.
    AutomaticContext,
}

/// Durable redaction-safe operational record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ObservabilityRecord {
    /// Operation category.
    pub operation: ObservabilityOperation,
    /// Elapsed wall-clock duration in whole milliseconds.
    pub duration_ms: u64,
    /// Count of accepted or returned candidates/items.
    pub item_count: usize,
    /// Provider implementation identifier, when a provider was invoked.
    pub provider: Option<String>,
    /// Model identifier, when a provider was invoked.
    pub model: Option<String>,
    /// Policy outcome, when policy was evaluated.
    pub policy_outcome: Option<PolicyAuditDisposition>,
    /// Stable error code only; never an error detail.
    pub error_code: Option<String>,
    /// Relevant visibility boundary, when known.
    pub scope: Option<MemoryScope>,
}

impl ObservabilityRecord {
    /// Returns an error-only record with no unsafe diagnostic data.
    #[must_use]
    pub fn failure(
        operation: ObservabilityOperation,
        duration_ms: u64,
        provider: Option<String>,
        model: Option<String>,
        error_code: impl Into<String>,
        scope: Option<MemoryScope>,
    ) -> Self {
        Self {
            operation,
            duration_ms,
            item_count: 0,
            provider,
            model,
            policy_outcome: None,
            error_code: Some(error_code.into()),
            scope,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serialized_records_reject_content_vector_refs_and_secrets() {
        let record = ObservabilityRecord::failure(
            ObservabilityOperation::ProviderCapture,
            3,
            Some("provider".to_owned()),
            Some("model".to_owned()),
            "SHIBA_VECTOR",
            None,
        );
        let encoded = serde_json::to_string(&record).expect("record serializes");

        for forbidden in ["content", "vector", "source_ref", "secret", "api_key"] {
            assert!(!encoded.contains(forbidden));
        }
    }
}
