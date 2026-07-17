package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/tufpublish"
)

func TestPublicationInput(t *testing.T) {
	private := ed25519.NewKeyFromSeed(make([]byte, ed25519.SeedSize))
	encoded := base64.StdEncoding.EncodeToString(private)
	for _, name := range []string{"TUF_ROOT_PRIVATE_KEY", "TUF_TARGETS_PRIVATE_KEY", "TUF_SNAPSHOT_PRIVATE_KEY", "TUF_TIMESTAMP_PRIVATE_KEY"} {
		t.Setenv(name, encoded)
	}
	target := filepath.Join(t.TempDir(), "bundle.tar.gz")
	if err := os.WriteFile(target, []byte("bundle"), 0o600); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Add(time.Hour)
	input, err := publicationInput([]string{target}, 1, now.Add(365*24*time.Hour), now, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tufpublish.Generate(input); err != nil {
		t.Fatal(err)
	}
}

func TestDecodeKeyRejectsMissingValue(t *testing.T) {
	t.Setenv("TUF_ROOT_PRIVATE_KEY", "")
	if _, err := decodeKey("TUF_ROOT_PRIVATE_KEY"); err == nil {
		t.Fatal("accepted missing TUF key")
	}
}
