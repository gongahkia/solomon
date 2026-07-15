// SPDX-License-Identifier: MIT

#![doc = include_str!("../README.md")]

use serde::Serialize;

pub mod anomaly;
pub mod api;
pub mod capture_worker;
pub mod collector;
pub mod config;
pub mod consolidation;
pub mod context_worker;
pub mod dedup;
pub mod embedding;
pub mod encryption;
pub mod extraction;
pub mod learned_policy;
pub mod model;
pub mod observability;
pub mod policy;
pub mod read_safety;
pub mod reconstruction;
pub mod retrieval;
pub mod review;
pub mod routing;
pub mod significance;
pub mod storage;
pub mod telemetry;
pub mod vector;

/// Current crate version, kept available to bindings and smoke tests.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Version of the public capability document.
pub const CAPABILITY_SCHEMA_VERSION: u32 = 1;

/// Versioned operations supported by this Shibahama build.
pub const CAPABILITIES: &[&str] = &[
    "write",
    "write_with_embedding",
    "recall",
    "stream_recall",
    "timeline",
    "stream_timeline",
    "invalidate",
    "reinforce",
    "why",
    "human_signals",
    "consolidate",
    "graph",
    "snapshot",
    "scope_promotion_authorization",
    "learned_policy_gates",
];

/// Versioned capability document for integrations and transports.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CapabilityDocument {
    /// Capability document schema version.
    pub schema_version: u32,
    /// Shibahama crate version.
    pub version: &'static str,
    /// Durable memory schema version.
    pub memory_schema_version: u16,
    /// Supported operations.
    pub capabilities: &'static [&'static str],
}

/// Returns the crate version.
#[must_use]
pub fn version() -> &'static str {
    VERSION
}

/// Returns the capabilities supported by this build.
#[must_use]
pub const fn capabilities() -> CapabilityDocument {
    CapabilityDocument {
        schema_version: CAPABILITY_SCHEMA_VERSION,
        version: VERSION,
        memory_schema_version: model::CURRENT_MEMORY_SCHEMA_VERSION,
        capabilities: CAPABILITIES,
    }
}

/// Returns whether this build supports an operation advertised in [`capabilities`].
#[must_use]
pub fn supports_capability(operation: &str) -> bool {
    CAPABILITIES.contains(&operation)
}

/// Returns a stable error when a requested optional operation is unsupported.
///
/// # Errors
///
/// Returns [`api::ShibahamaError::InvalidRequest`] when `operation` is not advertised.
pub fn require_capability(operation: &str) -> Result<(), api::ShibahamaError> {
    if supports_capability(operation) {
        Ok(())
    } else {
        Err(api::ShibahamaError::InvalidRequest(format!(
            "unsupported capability: {operation}"
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_matches_package_metadata() {
        assert_eq!(version(), env!("CARGO_PKG_VERSION"));
    }

    #[test]
    fn capabilities_are_versioned_and_queryable() {
        let capabilities = capabilities();

        assert_eq!(capabilities.schema_version, CAPABILITY_SCHEMA_VERSION);
        assert_eq!(capabilities.version, version());
        assert!(supports_capability("recall"));
        assert!(!supports_capability("unknown"));
        assert!(require_capability("recall").is_ok());
        assert!(matches!(
            require_capability("unknown"),
            Err(api::ShibahamaError::InvalidRequest(_))
        ));
    }
}
