// SPDX-License-Identifier: MIT

//! Encryption-at-rest extension points.

use aes_gcm::aead::rand_core::RngCore;
use aes_gcm::aead::{Aead, AeadCore, OsRng, Payload};
use aes_gcm::{Aes256Gcm, KeyInit};
use serde::{Deserialize, Serialize};
use thiserror::Error;

const AES_GCM_ENVELOPE_MAGIC: &[u8; 8] = b"SHIBENC1";
const AES_GCM_ENVELOPE_VERSION: u8 = 1;
const AES_GCM_NONCE_LEN: usize = 12;
const ENVELOPE_KEY_MAGIC: &[u8; 8] = b"SHIBENV1";
const ENVELOPE_KEY_VERSION: u8 = 1;
const ENVELOPE_METADATA_LEN: usize = 4;
const LOCAL_WRAPPED_KEY_VERSION: u8 = 1;
const DATA_KEY_LEN: usize = 32;

/// Error returned by encryption-at-rest hooks.
#[derive(Debug, Error)]
pub enum EncryptionError {
    /// Encryption provider rejected the operation.
    #[error("encryption provider failed: {0}")]
    Provider(String),
    /// Envelope-key metadata or ciphertext was malformed.
    #[error("envelope encryption payload was malformed: {0}")]
    Envelope(String),
    /// The key provider rejected a wrap or unwrap operation.
    #[error("envelope key provider failed: {0}")]
    KeyProvider(String),
}

/// Versioned metadata that identifies and unwraps one record data key.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EnvelopeKeyMetadata {
    /// Metadata schema version.
    pub schema_version: u8,
    /// Stable identifier for the key-provider implementation.
    pub provider: String,
    /// Provider-defined master-key or KMS-key identifier.
    pub key_id: String,
    /// Provider-owned wrapped 256-bit data key bytes.
    pub wrapped_data_key: Vec<u8>,
}

impl EnvelopeKeyMetadata {
    fn validate(&self) -> Result<(), EncryptionError> {
        if self.schema_version != ENVELOPE_KEY_VERSION
            || self.provider.is_empty()
            || self.key_id.is_empty()
            || self.wrapped_data_key.is_empty()
        {
            return Err(EncryptionError::Envelope(
                "envelope-key metadata is invalid".to_owned(),
            ));
        }

        Ok(())
    }
}

/// Pluggable key-encryption-key provider for per-record envelope encryption.
///
/// Implementations can wrap data keys with a local development key, an HSM, or an external KMS.
/// They must reject provider/key identifiers they do not own and must bind wrapping to `context`.
pub trait EnvelopeKeyProvider: Send + Sync {
    /// Stable identifier for this provider implementation.
    fn provider_id(&self) -> &str;

    /// Stable identifier for the active key-encryption key.
    fn key_id(&self) -> &str;

    /// Wraps one freshly generated 256-bit data key for an immutable storage context.
    ///
    /// # Errors
    ///
    /// Returns an error when the provider cannot protect the data key.
    fn wrap_data_key(
        &self,
        context: &[u8],
        data_key: &[u8; DATA_KEY_LEN],
    ) -> Result<Vec<u8>, EncryptionError>;

    /// Unwraps one data key after validating the provider metadata and storage context.
    ///
    /// # Errors
    ///
    /// Returns an error for missing, incorrect, or unauthorised keys and contexts.
    fn unwrap_data_key(
        &self,
        context: &[u8],
        metadata: &EnvelopeKeyMetadata,
    ) -> Result<[u8; DATA_KEY_LEN], EncryptionError>;
}

/// Local AES-256-GCM key provider for development and self-hosted deployments.
#[derive(Clone)]
pub struct LocalKeyProvider {
    key_id: String,
    cipher: Aes256Gcm,
}

impl LocalKeyProvider {
    /// Creates a local provider from a non-empty key identifier and 32-byte master key.
    #[must_use]
    pub fn new(key_id: impl Into<String>, master_key: [u8; DATA_KEY_LEN]) -> Self {
        Self {
            key_id: key_id.into(),
            cipher: Aes256Gcm::new(&master_key.into()),
        }
    }
}

impl std::fmt::Debug for LocalKeyProvider {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LocalKeyProvider")
            .field("provider", &self.provider_id())
            .field("key_id", &self.key_id)
            .finish_non_exhaustive()
    }
}

impl EnvelopeKeyProvider for LocalKeyProvider {
    fn provider_id(&self) -> &'static str {
        "local-aes-256-gcm"
    }

    fn key_id(&self) -> &str {
        &self.key_id
    }

    fn wrap_data_key(
        &self,
        context: &[u8],
        data_key: &[u8; DATA_KEY_LEN],
    ) -> Result<Vec<u8>, EncryptionError> {
        let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
        let ciphertext = self
            .cipher
            .encrypt(
                &nonce,
                Payload {
                    msg: data_key,
                    aad: context,
                },
            )
            .map_err(|error| EncryptionError::KeyProvider(error.to_string()))?;
        let mut wrapped = Vec::with_capacity(1 + nonce.len() + ciphertext.len());

        wrapped.push(LOCAL_WRAPPED_KEY_VERSION);
        wrapped.extend_from_slice(&nonce);
        wrapped.extend_from_slice(&ciphertext);

        Ok(wrapped)
    }

    fn unwrap_data_key(
        &self,
        context: &[u8],
        metadata: &EnvelopeKeyMetadata,
    ) -> Result<[u8; DATA_KEY_LEN], EncryptionError> {
        if metadata.provider != self.provider_id() || metadata.key_id != self.key_id() {
            return Err(EncryptionError::KeyProvider(
                "envelope key metadata does not match the configured local key".to_owned(),
            ));
        }
        if metadata.wrapped_data_key.len() < 1 + AES_GCM_NONCE_LEN
            || metadata.wrapped_data_key[0] != LOCAL_WRAPPED_KEY_VERSION
        {
            return Err(EncryptionError::KeyProvider(
                "wrapped local data key is malformed".to_owned(),
            ));
        }
        let nonce =
            aes_gcm::Nonce::from_slice(&metadata.wrapped_data_key[1..=AES_GCM_NONCE_LEN]);
        let plaintext = self
            .cipher
            .decrypt(
                nonce,
                Payload {
                    msg: &metadata.wrapped_data_key[1 + AES_GCM_NONCE_LEN..],
                    aad: context,
                },
            )
            .map_err(|error| EncryptionError::KeyProvider(error.to_string()))?;

        plaintext.try_into().map_err(|_| {
            EncryptionError::KeyProvider("wrapped local data key has an invalid length".to_owned())
        })
    }
}

/// Per-record envelope encryption backed by an external or local key provider.
///
/// A fresh data key is generated for every encrypted payload. The serialized envelope carries
/// provider metadata separately from the payload nonce and ciphertext, while both the wrapped key
/// and payload are authenticated against the immutable storage context.
pub struct EnvelopeEncryption<K> {
    key_provider: K,
}

impl<K> EnvelopeEncryption<K> {
    /// Creates an envelope-encryption provider from one key-encryption-key provider.
    #[must_use]
    pub const fn new(key_provider: K) -> Self {
        Self { key_provider }
    }

    /// Returns the provider that wraps per-record data keys.
    #[must_use]
    pub const fn key_provider(&self) -> &K {
        &self.key_provider
    }
}

impl<K: std::fmt::Debug> std::fmt::Debug for EnvelopeEncryption<K> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("EnvelopeEncryption")
            .field("key_provider", &self.key_provider)
            .finish()
    }
}

impl<K: EnvelopeKeyProvider> EncryptionAtRest for EnvelopeEncryption<K> {
    fn encrypt(&self, context: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        let mut data_key = [0_u8; DATA_KEY_LEN];
        OsRng.fill_bytes(&mut data_key);
        let metadata = EnvelopeKeyMetadata {
            schema_version: ENVELOPE_KEY_VERSION,
            provider: self.key_provider.provider_id().to_owned(),
            key_id: self.key_provider.key_id().to_owned(),
            wrapped_data_key: self.key_provider.wrap_data_key(context, &data_key)?,
        };

        metadata.validate()?;
        let metadata_bytes = serde_json::to_vec(&metadata)
            .map_err(|error| EncryptionError::Envelope(error.to_string()))?;
        let metadata_len = u32::try_from(metadata_bytes.len()).map_err(|_| {
            EncryptionError::Envelope("envelope-key metadata exceeds the supported size".to_owned())
        })?;
        let cipher = Aes256Gcm::new(&data_key.into());
        let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
        let ciphertext = cipher
            .encrypt(
                &nonce,
                Payload {
                    msg: plaintext,
                    aad: context,
                },
            )
            .map_err(|error| EncryptionError::Provider(error.to_string()))?;
        let mut envelope = Vec::with_capacity(
            ENVELOPE_KEY_MAGIC.len()
                + 1
                + ENVELOPE_METADATA_LEN
                + metadata_bytes.len()
                + nonce.len()
                + ciphertext.len(),
        );

        envelope.extend_from_slice(ENVELOPE_KEY_MAGIC);
        envelope.push(ENVELOPE_KEY_VERSION);
        envelope.extend_from_slice(&metadata_len.to_be_bytes());
        envelope.extend_from_slice(&metadata_bytes);
        envelope.extend_from_slice(&nonce);
        envelope.extend_from_slice(&ciphertext);

        Ok(envelope)
    }

    fn decrypt(&self, context: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        let (metadata, nonce_bytes, encrypted) = parse_envelope(ciphertext)?;
        let data_key = self.key_provider.unwrap_data_key(context, &metadata)?;
        let cipher = Aes256Gcm::new(&data_key.into());
        let nonce = aes_gcm::Nonce::from_slice(nonce_bytes);

        cipher
            .decrypt(
                nonce,
                Payload {
                    msg: encrypted,
                    aad: context,
                },
            )
            .map_err(|error| EncryptionError::Provider(error.to_string()))
    }
}

/// Reads envelope-key metadata without decrypting a payload.
///
/// # Errors
///
/// Returns an error when `ciphertext` is not a supported envelope payload.
pub fn envelope_key_metadata(ciphertext: &[u8]) -> Result<EnvelopeKeyMetadata, EncryptionError> {
    parse_envelope(ciphertext).map(|(metadata, _, _)| metadata)
}

fn parse_envelope(
    ciphertext: &[u8],
) -> Result<(EnvelopeKeyMetadata, &[u8], &[u8]), EncryptionError> {
    let fixed_len = ENVELOPE_KEY_MAGIC.len() + 1 + ENVELOPE_METADATA_LEN;
    if ciphertext.len() < fixed_len + AES_GCM_NONCE_LEN
        || !ciphertext.starts_with(ENVELOPE_KEY_MAGIC)
    {
        return Err(EncryptionError::Envelope(
            "encrypted payload is missing the Shibahama envelope".to_owned(),
        ));
    }
    if ciphertext[ENVELOPE_KEY_MAGIC.len()] != ENVELOPE_KEY_VERSION {
        return Err(EncryptionError::Envelope(
            "unsupported envelope encryption version".to_owned(),
        ));
    }
    let metadata_len_start = ENVELOPE_KEY_MAGIC.len() + 1;
    let metadata_len_end = metadata_len_start + ENVELOPE_METADATA_LEN;
    let metadata_len = u32::from_be_bytes(
        ciphertext[metadata_len_start..metadata_len_end]
            .try_into()
            .map_err(|_| EncryptionError::Envelope("invalid metadata length".to_owned()))?,
    ) as usize;
    let metadata_start = metadata_len_end;
    let metadata_end = metadata_start.checked_add(metadata_len).ok_or_else(|| {
        EncryptionError::Envelope("envelope-key metadata length overflowed".to_owned())
    })?;
    let nonce_end = metadata_end
        .checked_add(AES_GCM_NONCE_LEN)
        .ok_or_else(|| EncryptionError::Envelope("envelope nonce length overflowed".to_owned()))?;
    if nonce_end >= ciphertext.len() {
        return Err(EncryptionError::Envelope(
            "encrypted payload has no ciphertext".to_owned(),
        ));
    }
    let metadata: EnvelopeKeyMetadata =
        serde_json::from_slice(&ciphertext[metadata_start..metadata_end]).map_err(|_| {
            EncryptionError::Envelope("envelope-key metadata is malformed".to_owned())
        })?;

    metadata.validate()?;
    Ok((
        metadata,
        &ciphertext[metadata_end..nonce_end],
        &ciphertext[nonce_end..],
    ))
}

/// Hook for encrypting bytes before they are written to a storage backend.
pub trait EncryptionAtRest: Send + Sync {
    /// Returns true when this provider produces encrypted storage payloads.
    fn is_enabled(&self) -> bool {
        true
    }

    /// Encrypts `plaintext` for a backend-specific `context`.
    ///
    /// # Errors
    ///
    /// Returns an error when the provider cannot encrypt the payload.
    fn encrypt(&self, context: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EncryptionError>;

    /// Decrypts `ciphertext` for a backend-specific `context`.
    ///
    /// # Errors
    ///
    /// Returns an error when the provider cannot decrypt the payload.
    fn decrypt(&self, context: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EncryptionError>;
}

/// No-op encryption provider used until a real provider is configured.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct NoopEncryption;

impl EncryptionAtRest for NoopEncryption {
    fn is_enabled(&self) -> bool {
        false
    }

    fn encrypt(&self, _context: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        Ok(plaintext.to_vec())
    }

    fn decrypt(&self, _context: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        if ciphertext.starts_with(AES_GCM_ENVELOPE_MAGIC)
            || ciphertext.starts_with(ENVELOPE_KEY_MAGIC)
        {
            return Err(EncryptionError::Provider(
                "encrypted payload requires a configured encryption provider".to_owned(),
            ));
        }

        Ok(ciphertext.to_vec())
    }
}

/// AES-256-GCM encryption provider for redb value payloads.
#[derive(Clone)]
pub struct Aes256GcmEncryption {
    cipher: Aes256Gcm,
}

impl Aes256GcmEncryption {
    /// Creates an AES-256-GCM provider from a 32-byte key.
    #[must_use]
    pub fn new(key: [u8; 32]) -> Self {
        Self {
            cipher: Aes256Gcm::new(&key.into()),
        }
    }
}

impl std::fmt::Debug for Aes256GcmEncryption {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Aes256GcmEncryption")
            .field("provider", &"aes-256-gcm")
            .finish_non_exhaustive()
    }
}

impl EncryptionAtRest for Aes256GcmEncryption {
    fn encrypt(&self, context: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
        let ciphertext = self
            .cipher
            .encrypt(
                &nonce,
                Payload {
                    msg: plaintext,
                    aad: context,
                },
            )
            .map_err(|error| EncryptionError::Provider(error.to_string()))?;
        let mut envelope =
            Vec::with_capacity(AES_GCM_ENVELOPE_MAGIC.len() + 1 + nonce.len() + ciphertext.len());

        envelope.extend_from_slice(AES_GCM_ENVELOPE_MAGIC);
        envelope.push(AES_GCM_ENVELOPE_VERSION);
        envelope.extend_from_slice(&nonce);
        envelope.extend_from_slice(&ciphertext);

        Ok(envelope)
    }

    fn decrypt(&self, context: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        let header_len = AES_GCM_ENVELOPE_MAGIC.len() + 1 + AES_GCM_NONCE_LEN;

        if ciphertext.len() < header_len || !ciphertext.starts_with(AES_GCM_ENVELOPE_MAGIC) {
            return Err(EncryptionError::Provider(
                "encrypted payload is missing the Shibahama encryption envelope".to_owned(),
            ));
        }

        let version = ciphertext[AES_GCM_ENVELOPE_MAGIC.len()];
        if version != AES_GCM_ENVELOPE_VERSION {
            return Err(EncryptionError::Provider(format!(
                "unsupported encrypted payload version: {version}",
            )));
        }

        let nonce_start = AES_GCM_ENVELOPE_MAGIC.len() + 1;
        let nonce_end = nonce_start + AES_GCM_NONCE_LEN;
        let nonce = aes_gcm::Nonce::from_slice(&ciphertext[nonce_start..nonce_end]);
        let encrypted = &ciphertext[nonce_end..];

        self.cipher
            .decrypt(
                nonce,
                Payload {
                    msg: encrypted,
                    aad: context,
                },
            )
            .map_err(|error| EncryptionError::Provider(error.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn noop_encryption_round_trips_bytes() {
        let provider = NoopEncryption;
        let context = b"event-log";
        let plaintext = b"memory payload";
        let encrypted = provider
            .encrypt(context, plaintext)
            .expect("noop encrypt should work");
        let decrypted = provider
            .decrypt(context, &encrypted)
            .expect("noop decrypt should work");

        assert_eq!(encrypted, plaintext);
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn aes_gcm_encryption_round_trips_and_hides_plaintext() {
        let provider = Aes256GcmEncryption::new([7; 32]);
        let context = b"memory-items:item-1";
        let plaintext = b"sensitive memory payload";

        let encrypted = provider
            .encrypt(context, plaintext)
            .expect("encrypt should work");
        let decrypted = provider
            .decrypt(context, &encrypted)
            .expect("decrypt should work");

        assert_ne!(encrypted, plaintext);
        assert!(
            !encrypted
                .windows(plaintext.len())
                .any(|window| window == plaintext)
        );
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn aes_gcm_encryption_authenticates_context_and_key() {
        let provider = Aes256GcmEncryption::new([7; 32]);
        let wrong_key = Aes256GcmEncryption::new([8; 32]);
        let encrypted = provider
            .encrypt(b"memory-items:item-1", b"payload")
            .expect("encrypt should work");

        assert!(
            provider
                .decrypt(b"memory-items:item-2", &encrypted)
                .is_err()
        );
        assert!(
            wrong_key
                .decrypt(b"memory-items:item-1", &encrypted)
                .is_err()
        );
        assert!(
            NoopEncryption
                .decrypt(b"memory-items:item-1", &encrypted)
                .is_err()
        );
    }

    #[test]
    fn envelope_encryption_uses_distinct_record_keys_and_exposes_only_metadata() {
        let encryption = EnvelopeEncryption::new(LocalKeyProvider::new("development-kek", [9; 32]));
        let context = b"memory-items:item-1";
        let plaintext = b"envelope protected memory";
        let first = encryption
            .encrypt(context, plaintext)
            .expect("first envelope should encrypt");
        let second = encryption
            .encrypt(context, plaintext)
            .expect("second envelope should encrypt");
        let first_metadata = envelope_key_metadata(&first).expect("first metadata should parse");
        let second_metadata = envelope_key_metadata(&second).expect("second metadata should parse");

        assert_eq!(first_metadata.provider, "local-aes-256-gcm");
        assert_eq!(first_metadata.key_id, "development-kek");
        assert_ne!(
            first_metadata.wrapped_data_key,
            second_metadata.wrapped_data_key
        );
        assert_eq!(
            encryption
                .decrypt(context, &first)
                .expect("first envelope should decrypt"),
            plaintext
        );
        assert_eq!(
            encryption
                .decrypt(context, &second)
                .expect("second envelope should decrypt"),
            plaintext
        );
        assert!(
            !first
                .windows(plaintext.len())
                .any(|window| window == plaintext)
        );
    }

    #[test]
    fn envelope_encryption_fails_closed_for_missing_incorrect_or_rebound_keys() {
        let encryption =
            EnvelopeEncryption::new(LocalKeyProvider::new("development-kek", [10; 32]));
        let wrong_key = EnvelopeEncryption::new(LocalKeyProvider::new("development-kek", [11; 32]));
        let wrong_key_id = EnvelopeEncryption::new(LocalKeyProvider::new("rotated-kek", [10; 32]));
        let encrypted = encryption
            .encrypt(b"memory-items:item-1", b"payload")
            .expect("envelope should encrypt");

        assert!(
            NoopEncryption
                .decrypt(b"memory-items:item-1", &encrypted)
                .is_err()
        );
        assert!(
            wrong_key
                .decrypt(b"memory-items:item-1", &encrypted)
                .is_err()
        );
        assert!(
            wrong_key_id
                .decrypt(b"memory-items:item-1", &encrypted)
                .is_err()
        );
        assert!(
            encryption
                .decrypt(b"memory-items:item-2", &encrypted)
                .is_err()
        );
    }

    #[derive(Clone, Debug)]
    struct ExternalKeyProvider;

    impl EnvelopeKeyProvider for ExternalKeyProvider {
        fn provider_id(&self) -> &'static str {
            "external-test-kms"
        }

        fn key_id(&self) -> &'static str {
            "kms://example/key/1"
        }

        fn wrap_data_key(
            &self,
            context: &[u8],
            data_key: &[u8; DATA_KEY_LEN],
        ) -> Result<Vec<u8>, EncryptionError> {
            let mut wrapped = blake3::hash(context).as_bytes().to_vec();
            wrapped.extend(data_key.iter().rev().copied());

            Ok(wrapped)
        }

        fn unwrap_data_key(
            &self,
            context: &[u8],
            metadata: &EnvelopeKeyMetadata,
        ) -> Result<[u8; DATA_KEY_LEN], EncryptionError> {
            if metadata.provider != self.provider_id() || metadata.key_id != self.key_id() {
                return Err(EncryptionError::KeyProvider(
                    "external metadata was not issued by this provider".to_owned(),
                ));
            }
            if metadata.wrapped_data_key.len() != DATA_KEY_LEN * 2
                || metadata.wrapped_data_key[..DATA_KEY_LEN] != *blake3::hash(context).as_bytes()
            {
                return Err(EncryptionError::KeyProvider(
                    "external wrapped key does not match the record context".to_owned(),
                ));
            }
            let key = metadata
                .wrapped_data_key
                .iter()
                .skip(DATA_KEY_LEN)
                .rev()
                .copied()
                .collect::<Vec<_>>();

            key.try_into().map_err(|_| {
                EncryptionError::KeyProvider(
                    "external wrapped key has an invalid length".to_owned(),
                )
            })
        }
    }

    #[test]
    fn envelope_encryption_accepts_external_key_providers() {
        let encryption = EnvelopeEncryption::new(ExternalKeyProvider);
        let encrypted = encryption
            .encrypt(b"memory-items:item-1", b"external provider payload")
            .expect("external provider should wrap a data key");

        assert_eq!(
            encryption
                .decrypt(b"memory-items:item-1", &encrypted)
                .expect("external provider should unwrap a data key"),
            b"external provider payload"
        );
        assert!(
            encryption
                .decrypt(b"memory-items:item-2", &encrypted)
                .is_err()
        );
    }
}
