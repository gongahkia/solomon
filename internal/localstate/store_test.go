package localstate

import (
	"context"
	"testing"
	"time"
)

func TestOpenRejectsRelativeDirectory(t *testing.T) {
	if _, err := Open("state"); err == nil {
		t.Fatal("Open() accepted a relative directory")
	}
}

func TestLearnedRuleManagement(t *testing.T) {
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
	draft, err = store.UpdateDraft(context.Background(), draft.ID, "git sttaus", "git status --short")
	if err != nil || draft.NormalizedCorrection != "git status --short" {
		t.Fatalf("UpdateDraft() = %#v, %v", draft, err)
	}
	rule, err := store.ActivateDraft(context.Background(), draft.ID, "hint")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SetRuleAction(context.Background(), rule.ID, "rewrite"); err != nil {
		t.Fatal(err)
	}
	if err := store.SetRuleEnabled(context.Background(), rule.ID, false); err != nil {
		t.Fatal(err)
	}
	rules, err := store.ListActiveRules(context.Background())
	if err != nil || len(rules) != 0 {
		t.Fatalf("active rules = %#v, %v", rules, err)
	}
	if err := store.DeleteRule(context.Background(), rule.ID); err != nil {
		t.Fatal(err)
	}
	if err := store.PurgeLearning(context.Background()); err != nil {
		t.Fatal(err)
	}
}
