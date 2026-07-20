package config

import (
	"path/filepath"
	"testing"
)

func TestLocalLearningConsentPersists(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := Default()
	cfg.LocalLearningEnabled = true
	if err := Write(path, cfg); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadGlobal(path)
	if err != nil {
		t.Fatal(err)
	}
	if !loaded.LocalLearningEnabled {
		t.Fatal("local learning consent was not persisted")
	}
}
