package tufpublish

import (
	"crypto/ed25519"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/packs"
)

func TestGenerateProducesVerifiableTUFMetadata(t *testing.T) {
	now := time.Now().UTC()
	keys := testKeys()
	output, err := Generate(Input{
		Keys: keys,
		Targets: []Target{
			{Name: "close-enough-packs_v1.2.3.tar.gz", Data: []byte("packs")},
			{Name: "close-enough-packs_v1.2.3.tar.gz.sigstore.json", Data: []byte("signature")},
		},
		Version:          17,
		TargetsExpires:   now.Add(365 * 24 * time.Hour),
		SnapshotExpires:  now.Add(24 * time.Hour),
		TimestampExpires: now.Add(24 * time.Hour),
	})
	if err != nil {
		t.Fatal(err)
	}
	root, err := packs.VerifyRootBootstrap(output.Root, map[string]ed25519.PublicKey{"root": keys.Root.Public().(ed25519.PublicKey)})
	if err != nil {
		t.Fatal(err)
	}
	state := &packs.RegistryState{}
	timestamp, err := packs.VerifyTimestampAt(output.Timestamp, root, state, now)
	if err != nil {
		t.Fatal(err)
	}
	snapshot, err := packs.VerifySnapshotAt(output.Snapshot, root, timestamp, state, now)
	if err != nil {
		t.Fatal(err)
	}
	targets, err := packs.VerifyTargetsAt(output.Targets, root, snapshot, state, now)
	if err != nil {
		t.Fatal(err)
	}
	if len(targets.Targets) != 2 || targets.Targets["close-enough-packs_v1.2.3.tar.gz"].Length != len("packs") {
		t.Fatalf("targets = %#v", targets.Targets)
	}
}

func TestGenerateRejectsInvalidInput(t *testing.T) {
	keys := testKeys()
	input := Input{Keys: keys, Targets: []Target{{Name: "../escape", Data: []byte("pack")}}, Version: 1, TargetsExpires: time.Now().Add(365 * 24 * time.Hour), SnapshotExpires: time.Now().Add(time.Hour), TimestampExpires: time.Now().Add(time.Hour)}
	if _, err := Generate(input); err == nil {
		t.Fatal("accepted traversal target")
	}
	input.Targets[0].Name = "pack.json"
	input.TimestampExpires = time.Now().Add(-time.Hour)
	if _, err := Generate(input); err == nil {
		t.Fatal("accepted expired metadata")
	}
	keys.Timestamp = nil
	input.Keys = keys
	input.TimestampExpires = time.Now().Add(time.Hour)
	if _, err := Generate(input); err == nil {
		t.Fatal("accepted missing signing key")
	}
}

func testKeys() Keys {
	key := func(seed byte) ed25519.PrivateKey {
		data := make([]byte, ed25519.SeedSize)
		data[0] = seed
		return ed25519.NewKeyFromSeed(data)
	}
	return Keys{Root: key(1), Targets: key(2), Snapshot: key(3), Timestamp: key(4)}
}
