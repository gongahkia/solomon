package localstate

import (
	"context"
	"testing"
	"time"
)

func TestRecordAndRetainObservations(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	now := time.Now().UTC()
	observation, err := store.RecordObservation(context.Background(), Observation{Session: "session", FailedCommand: "git sttaus", CorrectedCommand: "git status", CreatedAt: now.Add(-48 * time.Hour)})
	if err != nil || observation.ID == 0 {
		t.Fatalf("RecordObservation() = %#v, %v", observation, err)
	}
	deleted, err := store.DeleteObservationsBefore(context.Background(), now.Add(-24*time.Hour))
	if err != nil || deleted != 1 {
		t.Fatalf("DeleteObservationsBefore() = %d, %v", deleted, err)
	}
}

func TestObservationRetentionPreservesBoundaryAndRecentEntries(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cutoff := time.Date(2026, time.July, 21, 0, 0, 0, 0, time.UTC)
	for _, observation := range []Observation{
		{Session: "old", FailedCommand: "git sttaus", CorrectedCommand: "git status", CreatedAt: cutoff.Add(-time.Second)},
		{Session: "boundary", FailedCommand: "git chekcout", CorrectedCommand: "git checkout", CreatedAt: cutoff},
		{Session: "recent", FailedCommand: "git pul", CorrectedCommand: "git pull", CreatedAt: cutoff.Add(time.Second)},
	} {
		if _, err := store.RecordObservation(context.Background(), observation); err != nil {
			t.Fatal(err)
		}
	}
	deleted, err := store.DeleteObservationsBefore(context.Background(), cutoff)
	if err != nil || deleted != 1 {
		t.Fatalf("DeleteObservationsBefore() = %d, %v", deleted, err)
	}
	rows, err := store.database.QueryContext(context.Background(), `SELECT session FROM observations ORDER BY created_at, id`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var sessions []string
	for rows.Next() {
		var session string
		if err := rows.Scan(&session); err != nil {
			t.Fatal(err)
		}
		sessions = append(sessions, session)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	if len(sessions) != 2 || sessions[0] != "boundary" || sessions[1] != "recent" {
		t.Fatalf("retained sessions = %#v", sessions)
	}
}
