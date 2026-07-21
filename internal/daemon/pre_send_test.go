package daemon

import (
	"context"
	"errors"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/packs"
)

func TestServiceUsesCuratedSafeRewrite(t *testing.T) {
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	service := Service{Config: config.Default(), Packs: resolver}
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
	cfg := config.Default()
	cfg.CuratedAutoCorrect = false
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
	service := Service{Config: config.Default(), Packs: resolver}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: "shell", Command: "git sttaus --token=super-secret"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "interrupt" || response.RewriteEligible || response.Risk != string(diagnose.RiskHigh) || response.Suggestion != "git status --token=[REDACTED]" {
		t.Fatalf("response = %+v", response)
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
