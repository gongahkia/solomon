package localstate

import (
	"context"
	"testing"
	"time"
)

func TestActivateDraftRequiresThreeObservations(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	observation := Observation{Session: "session", FailedCommand: "git sttaus", CorrectedCommand: "git status", CreatedAt: time.Now().UTC()}
	var draft Draft
	for range DraftEvidenceThreshold {
		draft, err = store.RecordLearningPair(context.Background(), observation)
		if err != nil {
			t.Fatal(err)
		}
	}
	drafts, err := store.ListReviewableDrafts(context.Background())
	if err != nil || len(drafts) != 1 || drafts[0].ID != draft.ID {
		t.Fatalf("reviewable drafts = %#v, %v", drafts, err)
	}
	rule, err := store.ActivateDraft(context.Background(), draft.ID, "hint")
	if err != nil || !rule.Enabled || rule.Action != "hint" {
		t.Fatalf("ActivateDraft() = %#v, %v", rule, err)
	}
	rules, err := store.ListActiveRules(context.Background())
	if err != nil || len(rules) != 1 || rules[0].ID != rule.ID {
		t.Fatalf("active rules = %#v, %v", rules, err)
	}
}
