package localstate

import (
	"context"
	"database/sql"
	"path/filepath"
	"strings"
	"testing"
)

func TestOpenInitializesSchemaVersion(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	var version int
	if err := store.database.QueryRowContext(context.Background(), "PRAGMA user_version").Scan(&version); err != nil {
		t.Fatal(err)
	}
	if version != 1 {
		t.Fatalf("schema version = %d", version)
	}
}

func TestOpenRejectsFutureSchemaVersion(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, databaseName)
	database, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := database.Exec("PRAGMA user_version = 2"); err != nil {
		database.Close()
		t.Fatal(err)
	}
	if err := database.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(directory); err == nil || !strings.Contains(err.Error(), "unsupported local state schema version") {
		t.Fatalf("Open() error = %v", err)
	}
}
