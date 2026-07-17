package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"path"
	"strings"
	"time"
)

type TUFTargets struct {
	Type    string                 `json:"_type"`
	Version int                    `json:"version"`
	Expires string                 `json:"expires"`
	Targets map[string]TUFMetaFile `json:"targets"`
}

func VerifyTargets(data []byte, root TUFRoot, snapshot TUFSnapshot) (TUFTargets, error) {
	return VerifyTargetsAt(data, root, snapshot, nil, time.Now())
}

func VerifyTargetsAt(data []byte, root TUFRoot, snapshot TUFSnapshot, state *RegistryState, now time.Time) (TUFTargets, error) {
	if err := validateRoot(root); err != nil {
		return TUFTargets{}, err
	}
	expected := snapshot.Meta["targets.json"].Version
	if expected < 1 {
		return TUFTargets{}, errors.New("snapshot lacks targets metadata")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var envelope TUFEnvelope
	if err := decoder.Decode(&envelope); err != nil {
		return TUFTargets{}, fmt.Errorf("parse targets envelope: %w", err)
	}
	decoder = json.NewDecoder(bytes.NewReader(envelope.Signed))
	decoder.DisallowUnknownFields()
	var targets TUFTargets
	if err := decoder.Decode(&targets); err != nil {
		return TUFTargets{}, fmt.Errorf("parse targets metadata: %w", err)
	}
	if targets.Type != "targets" || targets.Version != expected || targets.Expires == "" || len(targets.Targets) == 0 {
		return TUFTargets{}, errors.New("invalid targets metadata")
	}
	for target, metadata := range targets.Targets {
		if target == "" || path.IsAbs(target) || target == ".." || strings.HasPrefix(target, "../") || path.Clean(target) != target || metadata.Length < 0 || len(metadata.Hashes) == 0 {
			return TUFTargets{}, errors.New("invalid targets entry")
		}
	}
	payload, err := json.Marshal(targets)
	if err != nil {
		return TUFTargets{}, err
	}
	if err := verifyRootRoleSignatures(envelope.Signatures, payload, root, "targets"); err != nil {
		return TUFTargets{}, err
	}
	if err := state.Accept("targets", targets.Version, targets.Expires, now); err != nil {
		return TUFTargets{}, err
	}
	return targets, nil
}
