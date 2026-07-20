package daemon

import (
	"context"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/localstate"
	"github.com/gongahkia/close-enough/internal/packs"
)

func TestServiceMapsDecisionToProtocolResponse(t *testing.T) {
	service := Service{Engine: diagnose.New(diagnose.Options{Config: config.Default(), Path: t.TempDir(), CWD: t.TempDir()})}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "gti status"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Version != ProtocolVersion || response.Action != "none" {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceInterruptsCuratedHighRiskRule(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git push --force"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "interrupt" || response.Risk != "high" {
		t.Fatalf("response = %+v", response)
	}
	response, err = service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git push --force"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "submit" {
		t.Fatalf("second response = %+v", response)
	}
}

func TestServiceLearnsFailureThenSuccessfulCorrection(t *testing.T) {
	store, err := localstate.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	service := Service{Config: cfg, Store: store, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	request := Request{Version: ProtocolVersion, Session: "shell", Operation: PostFailureOperation, Command: "git sttaus", FailureOutput: "fatal: token=secret"}
	if _, err := service.Handle(context.Background(), request); err != nil {
		t.Fatal(err)
	}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Session: "shell", Operation: PostSuccessOperation, Command: "git status"}); err != nil {
		t.Fatal(err)
	}
	draft, err := store.DraftFor(context.Background(), "git sttaus", "git status")
	if err != nil || draft.EvidenceCount != 1 {
		t.Fatalf("draft = %#v, %v", draft, err)
	}
}

func TestServiceAppliesLearnedRuleWithinGlobalCeiling(t *testing.T) {
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	cfg.LearnedRuleActionCeiling = "hint"
	service := Service{Config: cfg, LearnedRules: []localstate.LearnedRule{{ID: 4, Failure: "git sttaus", Correction: "git status", Action: "rewrite", Enabled: true}}}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "hint" || response.Source != "learned" || response.RuleID != "4" {
		t.Fatalf("response = %+v", response)
	}
}
