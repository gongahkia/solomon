// SPDX-License-Identifier: MIT

//! Encryption-at-rest extension points.

use aes_gcm::aead::{Aead, AeadCore, OsRng, Payload};
use aes_gcm::{Aes256Gcm, KeyInit};
use thiserror::Error;

const AES_GCM_ENVELOPE_MAGIC: &[u8; 8] = b"SHIBENC1";
const AES_GCM_ENVELOPE_VERSION: u8 = 1;
const AES_GCM_NONCE_LEN: usize = 12;

/// Error returned by encryption-at-rest hooks.
#[derive(Debug, Error)]
pub enum EncryptionError {
    /// Encryption provider rejected the operation.
    #[error("encryption provider failed: {0}")]
    Provider(String),
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
        if ciphertext.starts_with(AES_GCM_ENVELOPE_MAGIC) {
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
}
