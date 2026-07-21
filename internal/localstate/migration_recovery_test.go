package localstate

import (
	"bytes"
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"
)

func TestOpenRollsBackPartialMigration(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, databaseName)
	database, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := database.Exec(`CREATE TABLE learned_rules (id INTEGER PRIMARY KEY)`); err != nil {
		database.Close()
		t.Fatal(err)
	}
	if err := database.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(directory); err == nil {
		t.Fatal("Open() succeeded with a conflicting migration table")
	}
	database, err = sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatal(err)
	}
	defer database.Close()
	var version int
	if err := database.QueryRowContext(context.Background(), `PRAGMA user_version`).Scan(&version); err != nil {
		t.Fatal(err)
	}
	if version != 0 {
		t.Fatalf("schema version = %d", version)
	}
	var count int
	if err := database.QueryRowContext(context.Background(), `SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name IN ('observations', 'learned_rule_drafts')`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 0 {
		t.Fatalf("partial migration tables = %d", count)
	}
}

func TestOpenRejectsCorruptDatabaseWithoutRewrite(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, databaseName)
	payload := []byte("not a SQLite database")
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(directory); err == nil {
		t.Fatal("Open() succeeded for corrupt database")
	}
	actual, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(actual, payload) {
		t.Fatalf("corrupt database was rewritten: %q", actual)
	}
}
