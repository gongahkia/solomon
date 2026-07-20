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
