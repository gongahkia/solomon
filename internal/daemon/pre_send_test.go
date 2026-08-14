package daemon

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/packs"
)

func rewriteConfig() config.Config {
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	return cfg
}

func interruptConfig() config.Config {
	cfg := config.Default()
	cfg.Mode = "interrupt"
	return cfg
}

func TestServiceUsesCuratedSafeRewrite(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "rewrite" || !response.RewriteEligible || response.Suggestion != "git status" || response.Source != "curated" || response.PackID != "core-git" || response.RuleID != "git-status-sttaus" {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceReportsCuratedRewriteEligibilityWithoutAutocorrectPermission(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	cfg := rewriteConfig()
	cfg.AutoApplySafe = false
	service := Service{Config: cfg, Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "hint" || !response.RewriteEligible {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceRejectsSecretBearingCuratedRewrite(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git sttaus --token=super-secret"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "none" || response.RewriteEligible || response.Suggestion != "" {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceDoesNotApplyAReadOnlyRuleToDestructiveSuffixes(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git brnach -D close-enough-audit-target"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "none" || response.RewriteEligible || response.Suggestion != "" {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceRendersCuratedCaptureTemplatesBeforePolicy(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "docker search --stars=5"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "rewrite" || response.Suggestion != "docker search --filter=stars=5" || response.Risk != string(diagnose.RiskSafe) {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceTreatsInstalledPacksAsHintOnly(t *testing.T) {
	installed := packs.Pack{SchemaVersion: 1, ID: "external-pack", Version: "1.0.0", Publisher: "publisher", Rules: []packs.Rule{{ID: "external-rule", Command: "external", Pattern: "^typo$", Replacement: "fixed", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only command"}}}
	resolver, err := packs.NewRuntimeResolverWithInstalled(nil, []packs.Pack{installed})
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "external typo"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "hint" || response.RewriteEligible || response.Source != "installed-pack" || response.Suggestion != "external fixed" {
		t.Fatalf("response = %+v", response)
	}
}

func TestServiceRestoresPendingRewriteOnceForItsSession(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell-a", Command: "git sttaus"}
	response, err := service.Handle(context.Background(), request)
	if err != nil || response.Action != "rewrite" || response.UndoToken == "" {
		t.Fatalf("pre-send response = %#v, %v", response, err)
	}
	undo := Request{Version: ProtocolVersion, Operation: UndoOperation, Session: "shell-b", Token: response.UndoToken}
	wrongSession, err := service.Handle(context.Background(), undo)
	if err != nil || wrongSession.Action != "none" {
		t.Fatalf("wrong-session undo = %#v, %v", wrongSession, err)
	}
	undo.Session = request.Session
	restored, err := service.Handle(context.Background(), undo)
	if err != nil || restored.Action != "edit-in-buffer" || restored.Suggestion != request.Command {
		t.Fatalf("undo response = %#v, %v", restored, err)
	}
	replayed, err := service.Handle(context.Background(), undo)
	if err != nil || replayed.Action != "none" {
		t.Fatalf("replayed undo = %#v, %v", replayed, err)
	}
}

func TestServiceExpiresPendingRewriteUndo(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, time.July, 21, 0, 0, 0, 0, time.UTC)
	service := Service{Config: rewriteConfig(), Packs: resolver, now: func() time.Time { return now }}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git sttaus"}
	response, err := service.Handle(context.Background(), request)
	if err != nil || response.UndoToken == "" {
		t.Fatalf("pre-send response = %#v, %v", response, err)
	}
	now = now.Add(time.Duration(service.Config.UndoTTLSeconds) * time.Second)
	undo, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: UndoOperation, Session: request.Session, Token: response.UndoToken})
	if err != nil || undo.Action != "none" {
		t.Fatalf("expired undo = %#v, %v", undo, err)
	}
}

func TestServiceKeepsOnlyLatestPendingRewriteUndo(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	first := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git sttaus"}
	firstResponse, err := service.Handle(context.Background(), first)
	if err != nil || firstResponse.UndoToken == "" {
		t.Fatalf("first response = %#v, %v", firstResponse, err)
	}
	second := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: first.Session, Command: "git statsu"}
	secondResponse, err := service.Handle(context.Background(), second)
	if err != nil || secondResponse.UndoToken == "" {
		t.Fatalf("second response = %#v, %v", secondResponse, err)
	}
	firstUndo, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: UndoOperation, Session: first.Session, Token: firstResponse.UndoToken})
	if err != nil || firstUndo.Action != "none" {
		t.Fatalf("superseded undo = %#v, %v", firstUndo, err)
	}
	secondUndo, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: UndoOperation, Session: second.Session, Token: secondResponse.UndoToken})
	if err != nil || secondUndo.Action != "edit-in-buffer" || secondUndo.Suggestion != second.Command {
		t.Fatalf("latest undo = %#v, %v", secondUndo, err)
	}
}

func TestServiceClearsUndoAfterCommandCompletion(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: rewriteConfig(), Packs: resolver}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git sttaus"}
	response, err := service.Handle(context.Background(), request)
	if err != nil || response.UndoToken == "" {
		t.Fatalf("pre-send response = %#v, %v", response, err)
	}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostSuccessOperation, Session: request.Session, Command: response.Suggestion}); err != nil {
		t.Fatal(err)
	}
	undo, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: UndoOperation, Session: request.Session, Token: response.UndoToken})
	if err != nil || undo.Action != "none" {
		t.Fatalf("completed-command undo = %#v, %v", undo, err)
	}
}

func TestServiceDoesNotIssueDisabledUndoTokens(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	cfg := rewriteConfig()
	cfg.UndoEnabled = false
	service := Service{Config: cfg, Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git sttaus"})
	if err != nil || response.Action != "rewrite" || response.UndoToken != "" {
		t.Fatalf("pre-send response = %#v, %v", response, err)
	}
}

func TestServicePropagatesCancellationDuringCuratedMatch(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	service := Service{Config: config.Default(), Packs: resolver}
	_, err = service.Handle(ctx, Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("curated match cancellation error = %v", err)
	}
}
