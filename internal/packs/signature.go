package packs

import (
	"crypto/ed25519"
	"errors"
	"os"
)

func VerifyDetachedSignature(payload, signature []byte, publicKey ed25519.PublicKey) error {
	if len(publicKey) != ed25519.PublicKeySize {
		return errors.New("invalid publisher public key")
	}
	if len(signature) != ed25519.SignatureSize {
		return errors.New("invalid detached signature")
	}
	if !ed25519.Verify(publicKey, payload, signature) {
		return errors.New("invalid detached signature")
	}
	return nil
}

func VerifyDetachedFiles(packPath, signaturePath string, publicKey ed25519.PublicKey) error {
	payload, err := os.ReadFile(packPath)
	if err != nil {
		return err
	}
	signature, err := os.ReadFile(signaturePath)
	if err != nil {
		return err
	}
	return VerifyDetachedSignature(payload, signature, publicKey)
}
