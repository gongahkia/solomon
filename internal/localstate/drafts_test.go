package localstate

import (
	"context"
	"testing"
	"time"
)

func TestRecordLearningPairAccumulatesDraftEvidence(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	observation := Observation{Session: "session", FailedCommand: "git sttaus", CorrectedCommand: "git status", CreatedAt: time.Now().UTC()}
	first, err := store.RecordLearningPair(context.Background(), observation)
	if err != nil || first.EvidenceCount != 1 {
		t.Fatalf("first pair = %#v, %v", first, err)
	}
	second, err := store.RecordLearningPair(context.Background(), observation)
	if err != nil || second.ID != first.ID || second.EvidenceCount != 2 {
		t.Fatalf("second pair = %#v, %v", second, err)
	}
}
