package packs

import (
	"bytes"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

type TUFMetaFile struct {
	Version int               `json:"version"`
	Length  int               `json:"length,omitempty"`
	Hashes  map[string]string `json:"hashes,omitempty"`
}

type TUFTimestamp struct {
	Type    string                 `json:"_type"`
	Version int                    `json:"version"`
	Expires string                 `json:"expires"`
	Meta    map[string]TUFMetaFile `json:"meta"`
}

func VerifyTimestamp(data []byte, root TUFRoot) (TUFTimestamp, error) {
	return VerifyTimestampAt(data, root, nil, time.Now())
}

func VerifyTimestampAt(data []byte, root TUFRoot, state *RegistryState, now time.Time) (TUFTimestamp, error) {
	if err := validateRoot(root); err != nil {
		return TUFTimestamp{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var envelope TUFEnvelope
	if err := decoder.Decode(&envelope); err != nil {
		return TUFTimestamp{}, fmt.Errorf("parse timestamp envelope: %w", err)
	}
	decoder = json.NewDecoder(bytes.NewReader(envelope.Signed))
	decoder.DisallowUnknownFields()
	var timestamp TUFTimestamp
	if err := decoder.Decode(&timestamp); err != nil {
		return TUFTimestamp{}, fmt.Errorf("parse timestamp metadata: %w", err)
	}
	if timestamp.Type != "timestamp" || timestamp.Version < 1 || timestamp.Expires == "" || timestamp.Meta["snapshot.json"].Version < 1 {
		return TUFTimestamp{}, errors.New("invalid timestamp metadata")
	}
	payload, err := json.Marshal(timestamp)
	if err != nil {
		return TUFTimestamp{}, err
	}
	if err := verifyRootRoleSignatures(envelope.Signatures, payload, root, "timestamp"); err != nil {
		return TUFTimestamp{}, err
	}
	if err := state.Accept("timestamp", timestamp.Version, timestamp.Expires, now); err != nil {
		return TUFTimestamp{}, err
	}
	return timestamp, nil
}

func verifyRootRoleSignatures(signatures []TUFSignature, payload []byte, root TUFRoot, roleName string) error {
	role, ok := root.Roles[roleName]
	if !ok || role.Threshold < 1 || role.Threshold > len(role.KeyIDs) {
		return fmt.Errorf("invalid %s role", roleName)
	}
	allowed := rootRoleKeys(role)
	verified := map[string]struct{}{}
	for _, signature := range signatures {
		if _, exists := allowed[signature.KeyID]; !exists {
			continue
		}
		publicKey := rootPublicKey(root.Keys[signature.KeyID])
		encoded, err := hex.DecodeString(signature.Sig)
		if err == nil && len(publicKey) == ed25519.PublicKeySize && len(encoded) == ed25519.SignatureSize && ed25519.Verify(publicKey, payload, encoded) {
			verified[signature.KeyID] = struct{}{}
		}
	}
	if len(verified) < role.Threshold {
		return fmt.Errorf("%s signature threshold is not met", roleName)
	}
	return nil
}
