package localstate

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestOpenBootstrapsSQLiteDatabase(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "state")
	store, err := Open(directory)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.database.ExecContext(context.Background(), "SELECT 1"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(directory, databaseName)); err != nil {
		t.Fatal(err)
	}
}
