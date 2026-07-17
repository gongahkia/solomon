package tufpublish

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"path"
	"strings"
	"time"

	"github.com/gongahkia/close-enough/internal/packs"
)

type Keys struct {
	Root      ed25519.PrivateKey
	Targets   ed25519.PrivateKey
	Snapshot  ed25519.PrivateKey
	Timestamp ed25519.PrivateKey
}

type Target struct {
	Name string
	Data []byte
}

type Input struct {
	Keys             Keys
	Targets          []Target
	Version          int
	TargetsExpires   time.Time
	SnapshotExpires  time.Time
	TimestampExpires time.Time
}

type Output struct {
	Root      []byte
	Targets   []byte
	Snapshot  []byte
	Timestamp []byte
}

func Generate(input Input) (Output, error) {
	if input.Version < 1 || input.TargetsExpires.IsZero() || input.SnapshotExpires.IsZero() || input.TimestampExpires.IsZero() || len(input.Targets) == 0 {
		return Output{}, errors.New("invalid TUF publication input")
	}
	now := time.Now()
	if !now.Before(input.TargetsExpires) || !now.Before(input.SnapshotExpires) || !now.Before(input.TimestampExpires) {
		return Output{}, errors.New("expired TUF publication input")
	}
	if err := validateKeys(input.Keys); err != nil {
		return Output{}, err
	}
	targets, err := targetMetadata(input.Targets, input.Version, input.TargetsExpires)
	if err != nil {
		return Output{}, err
	}
	targetsEnvelope, err := sign(targets, "targets", input.Keys.Targets)
	if err != nil {
		return Output{}, err
	}
	snapshot := packs.TUFSnapshot{
		Type:    "snapshot",
		Version: input.Version,
		Expires: input.SnapshotExpires.UTC().Format(time.RFC3339),
		Meta: map[string]packs.TUFMetaFile{
			"targets.json": metadata(targetsEnvelope, input.Version),
		},
	}
	snapshotEnvelope, err := sign(snapshot, "snapshot", input.Keys.Snapshot)
	if err != nil {
		return Output{}, err
	}
	timestamp := packs.TUFTimestamp{
		Type:    "timestamp",
		Version: input.Version,
		Expires: input.TimestampExpires.UTC().Format(time.RFC3339),
		Meta: map[string]packs.TUFMetaFile{
			"snapshot.json": metadata(snapshotEnvelope, input.Version),
		},
	}
	timestampEnvelope, err := sign(timestamp, "timestamp", input.Keys.Timestamp)
	if err != nil {
		return Output{}, err
	}
	root, err := rootMetadata(input.Keys, input.Version)
	if err != nil {
		return Output{}, err
	}
	rootEnvelope, err := sign(root, "root", input.Keys.Root)
	if err != nil {
		return Output{}, err
	}
	return Output{Root: rootEnvelope, Targets: targetsEnvelope, Snapshot: snapshotEnvelope, Timestamp: timestampEnvelope}, nil
}

func targetMetadata(targets []Target, version int, expiresAt time.Time) (packs.TUFTargets, error) {
	metas := make(map[string]packs.TUFMetaFile, len(targets))
	for _, target := range targets {
		if target.Name == "" || path.IsAbs(target.Name) || path.Clean(target.Name) != target.Name || target.Name == ".." || strings.HasPrefix(target.Name, "../") || len(target.Data) == 0 {
			return packs.TUFTargets{}, fmt.Errorf("invalid TUF target %q", target.Name)
		}
		if _, duplicate := metas[target.Name]; duplicate {
			return packs.TUFTargets{}, fmt.Errorf("duplicate TUF target %q", target.Name)
		}
		metas[target.Name] = metadata(target.Data, version)
	}
	return packs.TUFTargets{Type: "targets", Version: version, Expires: expiresAt.UTC().Format(time.RFC3339), Targets: metas}, nil
}

func rootMetadata(keys Keys, version int) (packs.TUFRoot, error) {
	roles := map[string]ed25519.PrivateKey{
		"root":      keys.Root,
		"targets":   keys.Targets,
		"snapshot":  keys.Snapshot,
		"timestamp": keys.Timestamp,
	}
	root := packs.TUFRoot{Type: "root", Version: version, Keys: map[string]packs.TUFKey{}, Roles: map[string]packs.TUFRole{}}
	for role, privateKey := range roles {
		publicKey := privateKey.Public().(ed25519.PublicKey)
		root.Keys[role] = tufKey(publicKey)
		root.Roles[role] = packs.TUFRole{KeyIDs: []string{role}, Threshold: 1}
	}
	return root, nil
}

func sign(value any, keyID string, privateKey ed25519.PrivateKey) ([]byte, error) {
	payload, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	envelope := packs.TUFEnvelope{Signed: payload, Signatures: []packs.TUFSignature{{KeyID: keyID, Sig: hex.EncodeToString(ed25519.Sign(privateKey, payload))}}}
	return json.Marshal(envelope)
}

func metadata(data []byte, version int) packs.TUFMetaFile {
	sum := sha256.Sum256(data)
	return packs.TUFMetaFile{Version: version, Length: len(data), Hashes: map[string]string{"sha256": hex.EncodeToString(sum[:])}}
}

func tufKey(publicKey ed25519.PublicKey) packs.TUFKey {
	key := packs.TUFKey{KeyType: "ed25519", Scheme: "ed25519"}
	key.KeyVal.Public = base64.RawStdEncoding.EncodeToString(publicKey)
	return key
}

func validateKeys(keys Keys) error {
	for _, key := range []ed25519.PrivateKey{keys.Root, keys.Targets, keys.Snapshot, keys.Timestamp} {
		if len(key) != ed25519.PrivateKeySize {
			return errors.New("invalid TUF signing key")
		}
	}
	return nil
}
