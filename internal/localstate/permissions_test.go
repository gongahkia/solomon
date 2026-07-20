package localstate

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOpenCreatesRestrictiveStateDatabase(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "state")
	store, err := Open(directory)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	info, err := os.Stat(filepath.Join(directory, databaseName))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("database permissions = %o", info.Mode().Perm())
	}
}
