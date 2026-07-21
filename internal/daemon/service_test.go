package daemon

import (
	"context"
	"slices"
	"strings"
	"testing"
	"time"

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
	if response.Version != ProtocolVersion || response.Action != "none" || response.Source != "heuristic" {
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

func TestServiceConfirmationTokenExpires(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, time.July, 21, 0, 0, 0, 0, time.UTC)
	service := Service{Config: config.Default(), Packs: resolver, now: func() time.Time { return now }}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git push --force"}
	response, err := service.Handle(context.Background(), request)
	if err != nil || response.Action != "interrupt" || response.ConfirmationToken == "" {
		t.Fatalf("pre-send response = %#v, %v", response, err)
	}
	now = now.Add(5*time.Second + time.Nanosecond)
	response, err = service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: ConfirmOperation, Session: request.Session, Command: request.Command, Token: response.ConfirmationToken})
	if err != nil || response.Action != "none" {
		t.Fatalf("expired confirmation response = %#v, %v", response, err)
	}
}

func TestServiceConfirmationTokenBindsExactCommand(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git push --force"}
	response, err := service.Handle(context.Background(), request)
	if err != nil || response.Action != "interrupt" || response.ConfirmationToken == "" {
		t.Fatalf("pre-send response = %#v, %v", response, err)
	}
	token := response.ConfirmationToken
	response, err = service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: ConfirmOperation, Session: request.Session, Command: "git reset --hard", Token: token})
	if err != nil || response.Action != "none" {
		t.Fatalf("modified confirmation response = %#v, %v", response, err)
	}
	response, err = service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: ConfirmOperation, Session: request.Session, Command: request.Command, Token: token})
	if err != nil || response.Action != "submit" {
		t.Fatalf("exact confirmation response = %#v, %v", response, err)
	}
}

func TestServiceInvalidatesConfirmationOnBufferModification(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git push --force"}
	response, err := service.Handle(context.Background(), request)
	if err != nil || response.Action != "interrupt" {
		t.Fatalf("initial response = %#v, %v", response, err)
	}
	response, err = service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: request.Session, Command: "git reset --hard"})
	if err != nil || response.Action != "interrupt" {
		t.Fatalf("modified response = %#v, %v", response, err)
	}
	response, err = service.Handle(context.Background(), request)
	if err != nil || response.Action != "interrupt" {
		t.Fatalf("restored response = %#v, %v", response, err)
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

func TestServiceAttachesGitFailureEvidenceToRepair(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Command: "git statsu", FailureOutput: "git: 'statsu' is not a git command.\n"})
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{{Kind: "git-unknown-subcommand", Value: "statsu"}}
	if response.Action != "hint" || response.Suggestion != "git status" || !slices.Equal(response.Evidence, want) {
		t.Fatalf("response = %#v, want evidence %#v", response, want)
	}
}

func TestServiceDoesNotAttachGitFailureEvidenceToOtherCommands(t *testing.T) {
	service := Service{Engine: diagnose.New(diagnose.Options{Config: config.Default(), Path: t.TempDir(), CWD: t.TempDir()})}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Command: "echo git", FailureOutput: "git: 'statsu' is not a git command.\n"})
	if err != nil {
		t.Fatal(err)
	}
	if len(response.Evidence) != 0 {
		t.Fatalf("response attached incompatible evidence: %#v", response)
	}
}

func TestServiceAttachesPackageManagerFailureEvidenceToRepair(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Command: "npm instal", FailureOutput: "npm error Missing script: \"instal\"\n"})
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{{Kind: "npm-missing-script", Value: "instal"}}
	if response.Action != "hint" || response.Suggestion != "npm install" || !slices.Equal(response.Evidence, want) {
		t.Fatalf("response = %#v, want evidence %#v", response, want)
	}
}

func TestServiceAttachesJavaScriptFailureEvidenceToRepair(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Command: "node --verison", FailureOutput: "node: bad option: --verison\n"})
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{{Kind: "node-unknown-option", Value: "--verison"}}
	if response.Action != "hint" || response.Suggestion != "node --version" || !slices.Equal(response.Evidence, want) {
		t.Fatalf("response = %#v, want evidence %#v", response, want)
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
