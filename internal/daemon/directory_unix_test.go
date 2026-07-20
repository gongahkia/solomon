//go:build !windows

package daemon

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPrepareDirectoryCreatesPrivateDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime")
	if err := PrepareDirectory(path); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o700 {
		t.Fatalf("permissions = %o", info.Mode().Perm())
	}
}

func TestPrepareDirectoryHardensAccessibleDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime")
	if err := os.Mkdir(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o750); err != nil {
		t.Fatal(err)
	}
	if err := PrepareDirectory(path); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o700 {
		t.Fatalf("permissions = %o", info.Mode().Perm())
	}
}
