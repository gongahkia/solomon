// SPDX-License-Identifier: MIT

//! Encryption-at-rest extension points.

use thiserror::Error;

/// Error returned by encryption-at-rest hooks.
#[derive(Debug, Error)]
pub enum EncryptionError {
    /// Encryption provider rejected the operation.
    #[error("encryption provider failed: {0}")]
    Provider(String),
}

/// Hook for encrypting bytes before they are written to a storage backend.
pub trait EncryptionAtRest {
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
    fn encrypt(&self, _context: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        Ok(plaintext.to_vec())
    }

    fn decrypt(&self, _context: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EncryptionError> {
        Ok(ciphertext.to_vec())
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
}
