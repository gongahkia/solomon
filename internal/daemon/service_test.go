package daemon

import (
	"context"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/localstate"
	"github.com/gongahkia/close-enough/internal/packs"
)

func TestNormalizedLearningCommand(t *testing.T) {
	for _, test := range []struct {
		command string
		want    string
		ok      bool
	}{
		{command: "  git\t sttaus  ", want: "git sttaus", ok: true},
		{command: "git status --token top-secret", want: "git status --token [REDACTED]"},
		{command: " \t "},
		{command: strings.Repeat("x", 8<<10+1)},
	} {
		got, ok := normalizedLearningCommand(test.command)
		if got != test.want || ok != test.ok {
			t.Fatalf("normalizedLearningCommand(%q) = %q, %t; want %q, %t", test.command, got, ok, test.want, test.ok)
		}
	}
}

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

func TestServiceConfirmEndpointRequiresMatchingToken(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	preSend := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git push --force"}
	response, err := service.Handle(context.Background(), preSend)
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "interrupt" || response.ConfirmationToken == "" {
		t.Fatalf("pre-send response = %+v", response)
	}
	token := response.ConfirmationToken
	confirm := Request{Version: ProtocolVersion, Operation: ConfirmOperation, Session: "shell", Command: "git push --force", Token: "wrong"}
	response, err = service.Handle(context.Background(), confirm)
	if err != nil || response.Action != "none" {
		t.Fatalf("wrong-token response = %+v, %v", response, err)
	}
	confirm.Token = token
	response, err = service.Handle(context.Background(), confirm)
	if err != nil || response.Action != "submit" {
		t.Fatalf("confirm response = %+v, %v", response, err)
	}
	response, err = service.Handle(context.Background(), confirm)
	if err != nil || response.Action != "none" {
		t.Fatalf("replayed response = %+v, %v", response, err)
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

func TestServiceRequiresSameSessionForLearningCorrection(t *testing.T) {
	store, err := localstate.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	service := Service{Config: cfg, Store: store, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Session: "first", Operation: PostFailureOperation, Command: "git sttaus"}); err != nil {
		t.Fatal(err)
	}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Session: "second", Operation: PostSuccessOperation, Command: "git status"}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.DraftFor(context.Background(), "git sttaus", "git status"); err == nil {
		t.Fatal("cross-session correction created learning evidence")
	}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Session: "first", Operation: PostSuccessOperation, Command: "git status"}); err != nil {
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
