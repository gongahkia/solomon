// SPDX-License-Identifier: MIT

//! Provider-neutral embedding contracts.

use serde::{Deserialize, Serialize};
use std::time::Duration;
use thiserror::Error;

/// Versioned capability offered by an embedding provider.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbeddingCapability {
    /// The provider can embed durable memory content.
    Document,
    /// The provider can embed recall queries.
    Query,
}

/// Stable identity and capabilities of one embedding model.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EmbeddingModelMetadata {
    /// Provider implementation identifier.
    pub provider: String,
    /// Model identifier.
    pub model: String,
    /// Model version.
    pub version: String,
    /// Exact vector dimension.
    pub dimensions: usize,
    /// Operations supported by the provider.
    pub capabilities: Vec<EmbeddingCapability>,
}

/// Input purpose passed to a provider without persistence side effects.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EmbeddingPurpose {
    /// Durable memory content being indexed.
    Document,
    /// Query text being used for recall.
    Query,
}

/// Stable provider failure category with retry metadata.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Error, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbeddingErrorKind {
    /// The provider cannot currently serve the request.
    #[error("provider unavailable")]
    Unavailable,
    /// The provider rejected input or model configuration.
    #[error("invalid embedding request")]
    InvalidRequest,
    /// Provider output or metadata violated the embedding contract.
    #[error("embedding contract mismatch")]
    ContractMismatch,
}

/// Provider error preserving stable machine-readable metadata.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
#[error("{kind}: {detail}")]
pub struct EmbeddingError {
    /// Stable failure category.
    pub kind: EmbeddingErrorKind,
    /// Whether retrying unchanged input can succeed.
    pub retryable: bool,
    /// Provider-safe diagnostic detail; callers must not include input content.
    pub detail: String,
}

/// Provider-neutral synchronous embedding interface.
pub trait EmbeddingProvider: Send + Sync {
    /// Returns model identity, dimensions, and supported operations.
    fn metadata(&self) -> EmbeddingModelMetadata;

    /// Embeds `text` for the requested purpose without logging content by contract.
    ///
    /// # Errors
    ///
    /// Returns provider-safe metadata when embedding cannot complete.
    fn embed(&self, text: &str, purpose: EmbeddingPurpose) -> Result<Vec<f32>, EmbeddingError>;
}

/// Cancellation boundary passed to remote embedding transports.
pub trait EmbeddingCancellation: Send + Sync {
    /// Returns whether the caller cancelled before the next remote attempt.
    fn is_cancelled(&self) -> bool;
}

/// No-op cancellation boundary used by synchronous provider calls.
#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancelled;

impl EmbeddingCancellation for NeverCancelled {
    fn is_cancelled(&self) -> bool {
        false
    }
}

/// Retry and timeout limits enforced by a remote embedding adapter.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RemoteEmbeddingPolicy {
    /// Maximum remote attempts, including the first request.
    pub max_attempts: usize,
    /// Per-attempt transport timeout.
    pub timeout: Duration,
}

impl Default for RemoteEmbeddingPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            timeout: Duration::from_secs(10),
        }
    }
}

/// Stable failure category returned by a remote embedding transport.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RemoteEmbeddingFailureKind {
    /// The transport exceeded its timeout.
    Timeout,
    /// The remote provider applied a rate limit.
    RateLimited,
    /// The remote provider is unavailable.
    Unavailable,
    /// The request was cancelled locally.
    Cancelled,
    /// The provider rejected the request.
    InvalidRequest,
}

/// Content-free remote embedding transport error.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteEmbeddingFailure {
    /// Stable failure category.
    pub kind: RemoteEmbeddingFailureKind,
    /// Provider-safe diagnostic without input content.
    pub detail: String,
}

/// Vendor-neutral remote embedding transport contract.
pub trait RemoteEmbeddingTransport: Send + Sync {
    /// Embeds one text input within `timeout`; implementations must not log input content.
    ///
    /// # Errors
    ///
    /// Returns a content-free transport failure for timeout, rate limit, cancellation, or rejection.
    fn embed(
        &self,
        text: &str,
        purpose: EmbeddingPurpose,
        timeout: Duration,
    ) -> Result<Vec<f32>, RemoteEmbeddingFailure>;
}

/// Remote provider adapter with bounded retry, timeout, cancellation, and metadata handling.
pub struct RemoteEmbeddingProvider<T> {
    metadata: EmbeddingModelMetadata,
    transport: T,
    policy: RemoteEmbeddingPolicy,
}

impl<T> RemoteEmbeddingProvider<T> {
    /// Creates a remote adapter with explicit model metadata and bounded transport policy.
    #[must_use]
    pub fn new(
        metadata: EmbeddingModelMetadata,
        transport: T,
        policy: RemoteEmbeddingPolicy,
    ) -> Self {
        Self {
            metadata,
            transport,
            policy,
        }
    }
}

impl<T: RemoteEmbeddingTransport> RemoteEmbeddingProvider<T> {
    /// Embeds with cancellation and bounded retries; no input content is logged by this adapter.
    ///
    /// # Errors
    ///
    /// Returns retry metadata after timeout, rate-limit, cancellation, or provider failure.
    pub fn embed_with_cancellation(
        &self,
        text: &str,
        purpose: EmbeddingPurpose,
        cancellation: &dyn EmbeddingCancellation,
    ) -> Result<Vec<f32>, EmbeddingError> {
        let attempts = self.policy.max_attempts.max(1);
        for attempt in 0..attempts {
            if cancellation.is_cancelled() {
                return Err(EmbeddingError {
                    kind: EmbeddingErrorKind::Unavailable,
                    retryable: false,
                    detail: "embedding request cancelled".to_owned(),
                });
            }
            match self.transport.embed(text, purpose, self.policy.timeout) {
                Ok(vector) => return Ok(vector),
                Err(error) => {
                    let retryable = matches!(
                        error.kind,
                        RemoteEmbeddingFailureKind::Timeout
                            | RemoteEmbeddingFailureKind::RateLimited
                            | RemoteEmbeddingFailureKind::Unavailable
                    );
                    if !retryable || attempt + 1 == attempts {
                        return Err(EmbeddingError {
                            kind: match error.kind {
                                RemoteEmbeddingFailureKind::InvalidRequest => {
                                    EmbeddingErrorKind::InvalidRequest
                                }
                                _ => EmbeddingErrorKind::Unavailable,
                            },
                            retryable,
                            detail: error.detail,
                        });
                    }
                }
            }
        }
        unreachable!("bounded retry loop always returns")
    }
}

impl<T: RemoteEmbeddingTransport> EmbeddingProvider for RemoteEmbeddingProvider<T> {
    fn metadata(&self) -> EmbeddingModelMetadata {
        self.metadata.clone()
    }

    fn embed(&self, text: &str, purpose: EmbeddingPurpose) -> Result<Vec<f32>, EmbeddingError> {
        self.embed_with_cancellation(text, purpose, &NeverCancelled)
    }
}

/// Deterministic local provider for tests, examples, and air-gapped development only.
///
/// Its byte-hash projection is intentionally unsuitable for semantic-quality or relevance claims.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeterministicLocalEmbeddingProvider {
    dimensions: usize,
}

impl DeterministicLocalEmbeddingProvider {
    /// Creates a deterministic local provider with a non-zero vector dimension.
    ///
    /// # Errors
    ///
    /// Returns an error when `dimensions` is zero.
    pub fn new(dimensions: usize) -> Result<Self, EmbeddingError> {
        if dimensions == 0 {
            return Err(EmbeddingError {
                kind: EmbeddingErrorKind::InvalidRequest,
                retryable: false,
                detail: "deterministic provider dimensions must be non-zero".to_owned(),
            });
        }

        Ok(Self { dimensions })
    }
}

impl EmbeddingProvider for DeterministicLocalEmbeddingProvider {
    fn metadata(&self) -> EmbeddingModelMetadata {
        EmbeddingModelMetadata {
            provider: "deterministic-local".to_owned(),
            model: "byte-hash-projection".to_owned(),
            version: "v1".to_owned(),
            dimensions: self.dimensions,
            capabilities: vec![EmbeddingCapability::Document, EmbeddingCapability::Query],
        }
    }

    fn embed(&self, text: &str, _purpose: EmbeddingPurpose) -> Result<Vec<f32>, EmbeddingError> {
        let mut vector = vec![0.0; self.dimensions];
        for (index, byte) in text.bytes().enumerate() {
            let slot = (index.wrapping_mul(31).wrapping_add(byte as usize)) % self.dimensions;
            vector[slot] += 1.0;
        }
        let norm = vector.iter().map(|value| value * value).sum::<f32>().sqrt();
        if norm > 0.0 {
            for value in &mut vector {
                *value /= norm;
            }
        }

        Ok(vector)
    }
}

/// Validates provider output against declared metadata before persistence.
///
/// # Errors
///
/// Returns [`EmbeddingError`] when the provider lacks the purpose or returns the wrong dimension.
pub fn validate_embedding(
    metadata: &EmbeddingModelMetadata,
    purpose: EmbeddingPurpose,
    vector: &[f32],
) -> Result<(), EmbeddingError> {
    let capability = match purpose {
        EmbeddingPurpose::Document => EmbeddingCapability::Document,
        EmbeddingPurpose::Query => EmbeddingCapability::Query,
    };
    if !metadata.capabilities.contains(&capability) {
        return Err(EmbeddingError {
            kind: EmbeddingErrorKind::InvalidRequest,
            retryable: false,
            detail: "embedding purpose is unsupported".to_owned(),
        });
    }
    if vector.len() != metadata.dimensions {
        return Err(EmbeddingError {
            kind: EmbeddingErrorKind::ContractMismatch,
            retryable: false,
            detail: "embedding dimensions do not match provider metadata".to_owned(),
        });
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn deterministic_provider_is_platform_stable_and_offline() {
        let provider = DeterministicLocalEmbeddingProvider::new(8).expect("dimension is valid");
        let first = provider
            .embed("air-gapped fixture", EmbeddingPurpose::Document)
            .expect("local embed should work");
        let second = provider
            .embed("air-gapped fixture", EmbeddingPurpose::Query)
            .expect("local embed should work");

        assert_eq!(first, second);
        assert_eq!(first.len(), 8);
        assert_eq!(provider.metadata().provider, "deterministic-local");
    }

    #[test]
    fn remote_provider_retries_transient_failures_and_honors_cancellation() {
        struct RetryTransport(AtomicUsize);
        impl RemoteEmbeddingTransport for RetryTransport {
            fn embed(
                &self,
                _text: &str,
                _purpose: EmbeddingPurpose,
                _timeout: Duration,
            ) -> Result<Vec<f32>, RemoteEmbeddingFailure> {
                if self.0.fetch_add(1, Ordering::SeqCst) == 0 {
                    return Err(RemoteEmbeddingFailure {
                        kind: RemoteEmbeddingFailureKind::RateLimited,
                        detail: "rate limited".to_owned(),
                    });
                }
                Ok(vec![1.0, 0.0])
            }
        }
        struct Cancelled;
        impl EmbeddingCancellation for Cancelled {
            fn is_cancelled(&self) -> bool {
                true
            }
        }

        let provider = RemoteEmbeddingProvider::new(
            EmbeddingModelMetadata {
                provider: "fake".to_owned(),
                model: "fake-model".to_owned(),
                version: "v1".to_owned(),
                dimensions: 2,
                capabilities: vec![EmbeddingCapability::Document, EmbeddingCapability::Query],
            },
            RetryTransport(AtomicUsize::new(0)),
            RemoteEmbeddingPolicy::default(),
        );

        assert_eq!(
            provider
                .embed("content is not logged", EmbeddingPurpose::Document)
                .expect("second attempt should succeed"),
            vec![1.0, 0.0]
        );
        assert!(matches!(
            provider.embed_with_cancellation("ignored", EmbeddingPurpose::Query, &Cancelled),
            Err(EmbeddingError {
                retryable: false,
                ..
            })
        ));
    }
}
