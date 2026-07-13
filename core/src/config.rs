// SPDX-License-Identifier: MIT

//! Strict runtime configuration for embedded, server, and MCP hosts.

use crate::api::{ScopeMode, ShibahamaConfig};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use thiserror::Error;

/// Supported runtime configuration schema version.
pub const RUNTIME_CONFIG_SCHEMA_VERSION: u16 = 1;

/// Error returned when runtime configuration is malformed or unsafe.
#[derive(Debug, Error, Eq, PartialEq)]
pub enum RuntimeConfigError {
    /// Input was not a valid configuration document.
    #[error("runtime configuration JSON is invalid")]
    Decode,
    /// Input uses an unsupported configuration schema.
    #[error("unsupported runtime configuration schema")]
    UnsupportedSchema,
    /// A required field was empty or inconsistent.
    #[error("runtime configuration contains an invalid value")]
    InvalidValue,
}

/// Versioned configuration supplied before opening an engine or service.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeConfig {
    /// Configuration schema version.
    pub schema_version: u16,
    /// Durable-storage configuration.
    pub storage: StorageRuntimeConfig,
    /// Embedding-provider configuration.
    pub provider: ProviderRuntimeConfig,
    /// Core policy configuration.
    pub policy: PolicyRuntimeConfig,
    /// Host authentication configuration.
    pub auth: AuthRuntimeConfig,
    /// Content-safe observability configuration.
    pub observability: ObservabilityRuntimeConfig,
}

/// Durable storage settings.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StorageRuntimeConfig {
    /// Path to the durable local store.
    pub path: PathBuf,
    /// At-rest encryption requirement selected by the host.
    pub encryption: StorageEncryptionMode,
}

/// At-rest encryption mode selected by configuration.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StorageEncryptionMode {
    /// Allow an unencrypted store for embedded development only.
    DevelopmentOnly,
    /// Require an encryption provider before the host opens a shared store.
    Required,
}

/// Provider configuration used to validate vector compatibility.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderRuntimeConfig {
    /// Provider implementation kind selected by the host.
    pub kind: ProviderKind,
    /// Stable provider/model identifier.
    pub model: String,
    /// Exact embedding dimensionality.
    pub dimensions: usize,
    /// Optional remote endpoint; it is never rendered in effective configuration.
    pub endpoint: Option<String>,
}

/// Provider implementation category.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderKind {
    /// Caller submits already-computed vectors.
    CallerSupplied,
    /// Host uses a deterministic local provider.
    Local,
    /// Host delegates embedding work to a configured remote provider.
    Remote,
}

/// Policy settings available before capture/recall policy models are installed.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyRuntimeConfig {
    /// Require explicit scope contexts at public core boundaries.
    pub require_explicit_scope: bool,
    /// Enable the automatic-capture worker in addition to its capture-policy checks.
    pub automatic_capture_enabled: bool,
}

/// Host authentication settings.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthRuntimeConfig {
    /// Authentication mechanism selected by the host.
    pub mode: AuthMode,
    /// Optional secret for API-key deployments.
    pub api_key: Option<String>,
}

/// Authentication mechanism selected by the host.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthMode {
    /// Embedded host owns authentication outside Shibahama.
    External,
    /// HTTP host requires an API key.
    ApiKey,
}

/// Content-safe observability settings.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObservabilityRuntimeConfig {
    /// Emit structured operational records.
    pub enabled: bool,
    /// Content logging must remain disabled.
    pub include_content: bool,
}

/// Safe inspection view of the active runtime configuration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RedactedRuntimeConfig {
    /// Configuration schema version.
    pub schema_version: u16,
    /// Effective storage settings.
    pub storage: StorageRuntimeConfig,
    /// Effective provider settings with endpoint withheld.
    pub provider: RedactedProviderRuntimeConfig,
    /// Effective policy settings.
    pub policy: PolicyRuntimeConfig,
    /// Effective authentication settings without key material.
    pub auth: RedactedAuthRuntimeConfig,
    /// Effective observability settings.
    pub observability: ObservabilityRuntimeConfig,
}

/// Provider settings safe to inspect.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RedactedProviderRuntimeConfig {
    /// Provider implementation category.
    pub kind: ProviderKind,
    /// Stable provider/model identifier.
    pub model: String,
    /// Exact embedding dimensionality.
    pub dimensions: usize,
    /// Whether a remote endpoint was supplied.
    pub endpoint_configured: bool,
}

/// Authentication settings safe to inspect.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RedactedAuthRuntimeConfig {
    /// Authentication mechanism selected by the host.
    pub mode: AuthMode,
    /// Whether API-key material was supplied.
    pub api_key_configured: bool,
}

impl RuntimeConfig {
    /// Decodes and validates one strict JSON configuration document.
    ///
    /// # Errors
    ///
    /// Returns an error when the document has unknown fields or invalid values.
    pub fn from_json(input: &str) -> Result<Self, RuntimeConfigError> {
        let config: Self = serde_json::from_str(input).map_err(|_| RuntimeConfigError::Decode)?;
        config.validate()?;

        Ok(config)
    }

    /// Validates configuration before a store or provider opens.
    ///
    /// # Errors
    ///
    /// Returns an error when a setting is incompatible with the selected host mode.
    pub fn validate(&self) -> Result<(), RuntimeConfigError> {
        if self.schema_version != RUNTIME_CONFIG_SCHEMA_VERSION {
            return Err(RuntimeConfigError::UnsupportedSchema);
        }
        if self.storage.path.as_os_str().is_empty()
            || self.provider.model.trim().is_empty()
            || self.provider.dimensions == 0
            || self.observability.include_content
        {
            return Err(RuntimeConfigError::InvalidValue);
        }
        match self.provider.kind {
            ProviderKind::Remote if self.provider.endpoint.as_deref().is_none_or(str::is_empty) => {
                return Err(RuntimeConfigError::InvalidValue);
            }
            ProviderKind::CallerSupplied | ProviderKind::Local
                if self.provider.endpoint.is_some() =>
            {
                return Err(RuntimeConfigError::InvalidValue);
            }
            ProviderKind::CallerSupplied | ProviderKind::Local | ProviderKind::Remote => {}
        }
        match self.auth.mode {
            AuthMode::ApiKey if self.auth.api_key.as_deref().is_none_or(str::is_empty) => {
                Err(RuntimeConfigError::InvalidValue)
            }
            AuthMode::External if self.auth.api_key.is_some() => {
                Err(RuntimeConfigError::InvalidValue)
            }
            AuthMode::ApiKey | AuthMode::External => Ok(()),
        }
    }

    /// Builds the corresponding core engine configuration.
    #[must_use]
    pub fn engine_config(&self) -> ShibahamaConfig {
        ShibahamaConfig {
            scope_mode: if self.policy.require_explicit_scope {
                ScopeMode::RequireExplicit
            } else {
                ScopeMode::LocalSingleStore
            },
            automatic_capture_enabled: self.policy.automatic_capture_enabled,
            ..ShibahamaConfig::default()
        }
    }

    /// Returns a complete but secret-free effective configuration view.
    #[must_use]
    pub fn redacted(&self) -> RedactedRuntimeConfig {
        RedactedRuntimeConfig {
            schema_version: self.schema_version,
            storage: self.storage.clone(),
            provider: RedactedProviderRuntimeConfig {
                kind: self.provider.kind,
                model: self.provider.model.clone(),
                dimensions: self.provider.dimensions,
                endpoint_configured: self.provider.endpoint.is_some(),
            },
            policy: self.policy,
            auth: RedactedAuthRuntimeConfig {
                mode: self.auth.mode,
                api_key_configured: self.auth.api_key.is_some(),
            },
            observability: self.observability,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::{Shibahama, ShibahamaError};
    use crate::vector::HnswVectorIndex;
    use tempfile::tempdir;

    fn valid_config() -> RuntimeConfig {
        RuntimeConfig {
            schema_version: RUNTIME_CONFIG_SCHEMA_VERSION,
            storage: StorageRuntimeConfig {
                path: PathBuf::from("memory.redb"),
                encryption: StorageEncryptionMode::DevelopmentOnly,
            },
            provider: ProviderRuntimeConfig {
                kind: ProviderKind::CallerSupplied,
                model: "caller-vector/v1".to_owned(),
                dimensions: 384,
                endpoint: None,
            },
            policy: PolicyRuntimeConfig {
                require_explicit_scope: true,
                automatic_capture_enabled: false,
            },
            auth: AuthRuntimeConfig {
                mode: AuthMode::External,
                api_key: None,
            },
            observability: ObservabilityRuntimeConfig {
                enabled: true,
                include_content: false,
            },
        }
    }

    #[test]
    fn strict_config_rejects_unknown_and_unsafe_values() {
        let unknown = r#"{"schema_version":1,"storage":{"path":"m.redb","encryption":"development_only"},"provider":{"kind":"caller_supplied","model":"m","dimensions":2},"policy":{"require_explicit_scope":true,"automatic_capture_enabled":false},"auth":{"mode":"external","api_key":null},"observability":{"enabled":true,"include_content":false},"unknown":true}"#;
        assert!(matches!(
            RuntimeConfig::from_json(unknown),
            Err(RuntimeConfigError::Decode)
        ));
        let mut unsafe_config = valid_config();
        unsafe_config.observability.include_content = true;
        assert_eq!(
            unsafe_config.validate(),
            Err(RuntimeConfigError::InvalidValue)
        );
    }

    #[test]
    fn runtime_config_can_explicitly_enable_automatic_capture() {
        let mut config = valid_config();
        config.policy.automatic_capture_enabled = true;

        config.validate().expect("automatic capture can be enabled");
        assert!(config.engine_config().automatic_capture_enabled);
    }

    #[test]
    fn redacted_config_hides_endpoint_and_api_key() {
        let mut config = valid_config();
        config.provider = ProviderRuntimeConfig {
            kind: ProviderKind::Remote,
            model: "remote/v1".to_owned(),
            dimensions: 384,
            endpoint: Some("https://secret.example/v1".to_owned()),
        };
        config.auth = AuthRuntimeConfig {
            mode: AuthMode::ApiKey,
            api_key: Some("never-render-this-key".to_owned()),
        };
        let redacted = serde_json::to_string(&config.redacted()).expect("config should serialize");

        assert!(!redacted.contains("secret.example"));
        assert!(!redacted.contains("never-render-this-key"));
        assert!(config.redacted().auth.api_key_configured);
        assert!(config.redacted().provider.endpoint_configured);
    }

    #[test]
    fn engine_open_rejects_dimension_mismatch_before_creating_store() {
        let directory = tempdir().expect("temporary directory should be created");
        let path = directory.path().join("memory.redb");
        let mut config = valid_config();
        config.storage.path = path.clone();
        config.provider.dimensions = 3;

        assert!(matches!(
            Shibahama::open_from_runtime_config(&config, HnswVectorIndex::new(2)),
            Err(ShibahamaError::InvalidRequest(_))
        ));
        assert!(!path.exists());
    }
}
