package packs

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
)

type TUFSignature struct {
	KeyID string `json:"keyid"`
	Sig   string `json:"sig"`
}

type TUFEnvelope struct {
	Signatures []TUFSignature  `json:"signatures"`
	Signed     json.RawMessage `json:"signed"`
}

type TUFKey struct {
	KeyType string `json:"keytype"`
	Scheme  string `json:"scheme"`
	KeyVal  struct {
		Public string `json:"public"`
	} `json:"keyval"`
}

type TUFRole struct {
	KeyIDs    []string `json:"keyids"`
	Threshold int      `json:"threshold"`
}

type TUFRoot struct {
	Type    string             `json:"_type"`
	Version int                `json:"version"`
	Keys    map[string]TUFKey  `json:"keys"`
	Roles   map[string]TUFRole `json:"roles"`
}

func CanonicalRootPayload(root TUFRoot) ([]byte, error) { return json.Marshal(root) }

func VerifyRootBootstrap(data []byte, trusted map[string]ed25519.PublicKey) (TUFRoot, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var envelope TUFEnvelope
	if err := decoder.Decode(&envelope); err != nil {
		return TUFRoot{}, fmt.Errorf("parse root envelope: %w", err)
	}
	if len(envelope.Signed) == 0 {
		return TUFRoot{}, errors.New("root envelope has no signed payload")
	}
	decoder = json.NewDecoder(bytes.NewReader(envelope.Signed))
	decoder.DisallowUnknownFields()
	var root TUFRoot
	if err := decoder.Decode(&root); err != nil {
		return TUFRoot{}, fmt.Errorf("parse root metadata: %w", err)
	}
	if err := validateRoot(root); err != nil {
		return TUFRoot{}, err
	}
	payload, err := CanonicalRootPayload(root)
	if err != nil {
		return TUFRoot{}, err
	}
	role := root.Roles["root"]
	verified := map[string]struct{}{}
	for _, signature := range envelope.Signatures {
		if _, allowed := rootRoleKeys(role)[signature.KeyID]; !allowed {
			continue
		}
		publicKey, trustedKey := trusted[signature.KeyID]
		if !trustedKey || !bytes.Equal(publicKey, rootPublicKey(root.Keys[signature.KeyID])) {
			continue
		}
		encoded, err := hex.DecodeString(signature.Sig)
		if err == nil && len(encoded) == ed25519.SignatureSize && ed25519.Verify(publicKey, payload, encoded) {
			verified[signature.KeyID] = struct{}{}
		}
	}
	if len(verified) < role.Threshold {
		return TUFRoot{}, errors.New("root signature threshold is not met")
	}
	return root, nil
}

func validateRoot(root TUFRoot) error {
	if root.Type != "root" || root.Version < 1 || len(root.Keys) == 0 {
		return errors.New("invalid root metadata")
	}
	role, ok := root.Roles["root"]
	if !ok || role.Threshold < 1 || role.Threshold > len(role.KeyIDs) {
		return errors.New("invalid root role")
	}
	seen := map[string]struct{}{}
	for _, id := range role.KeyIDs {
		if _, duplicate := seen[id]; duplicate || root.Keys[id].KeyType != "ed25519" || root.Keys[id].Scheme != "ed25519" || len(rootPublicKey(root.Keys[id])) != ed25519.PublicKeySize {
			return errors.New("invalid root role key")
		}
		seen[id] = struct{}{}
	}
	return nil
}

func rootRoleKeys(role TUFRole) map[string]struct{} {
	keys := make(map[string]struct{}, len(role.KeyIDs))
	for _, id := range role.KeyIDs {
		keys[id] = struct{}{}
	}
	return keys
}

func rootPublicKey(key TUFKey) ed25519.PublicKey {
	decoded, err := base64.RawStdEncoding.DecodeString(key.KeyVal.Public)
	if err != nil {
		return nil
	}
	return ed25519.PublicKey(decoded)
}
