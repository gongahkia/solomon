package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
)

type TUFSnapshot struct {
	Type    string                 `json:"_type"`
	Version int                    `json:"version"`
	Expires string                 `json:"expires"`
	Meta    map[string]TUFMetaFile `json:"meta"`
}

func VerifySnapshot(data []byte, root TUFRoot, timestamp TUFTimestamp) (TUFSnapshot, error) {
	if err := validateRoot(root); err != nil {
		return TUFSnapshot{}, err
	}
	expected := timestamp.Meta["snapshot.json"].Version
	if expected < 1 {
		return TUFSnapshot{}, errors.New("timestamp lacks snapshot metadata")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var envelope TUFEnvelope
	if err := decoder.Decode(&envelope); err != nil {
		return TUFSnapshot{}, fmt.Errorf("parse snapshot envelope: %w", err)
	}
	decoder = json.NewDecoder(bytes.NewReader(envelope.Signed))
	decoder.DisallowUnknownFields()
	var snapshot TUFSnapshot
	if err := decoder.Decode(&snapshot); err != nil {
		return TUFSnapshot{}, fmt.Errorf("parse snapshot metadata: %w", err)
	}
	if snapshot.Type != "snapshot" || snapshot.Version != expected || snapshot.Expires == "" || len(snapshot.Meta) == 0 {
		return TUFSnapshot{}, errors.New("invalid snapshot metadata")
	}
	payload, err := json.Marshal(snapshot)
	if err != nil {
		return TUFSnapshot{}, err
	}
	if err := verifyRootRoleSignatures(envelope.Signatures, payload, root, "snapshot"); err != nil {
		return TUFSnapshot{}, err
	}
	return snapshot, nil
}
