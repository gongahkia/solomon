package securetemp

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestCleanupRemovesRestrictiveTemporaryFile(t *testing.T) {
	file, err := Create(t.TempDir(), "temporary-*")
	if err != nil {
		t.Fatal(err)
	}
	path := file.Path()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o600 {
		t.Fatalf("permissions = %o, want 600", info.Mode().Perm())
	}
	if _, err := file.Write([]byte("secret")); err != nil {
		t.Fatal(err)
	}
	if err := file.Cleanup(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("temporary file remains: %v", err)
	}
	if err := file.Cleanup(); err != nil {
		t.Fatal(err)
	}
}

func TestCommitAtomicallyReplacesTarget(t *testing.T) {
	directory := t.TempDir()
	target := filepath.Join(directory, "config.json")
	if err := os.WriteFile(target, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	file, err := Create(directory, ".config.json.tmp-*")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.Write([]byte("new")); err != nil {
		t.Fatal(err)
	}
	if err := file.Commit(target); err != nil {
		t.Fatal(err)
	}
	if err := file.Cleanup(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "new" {
		t.Fatalf("target = %q, want new", data)
	}
}

func TestCreateFailsWithoutParentDirectory(t *testing.T) {
	_, err := Create(filepath.Join(t.TempDir(), "missing"), "temporary-*")
	if err == nil {
		t.Fatal("expected create failure")
	}
}
