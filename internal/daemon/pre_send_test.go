package daemon

import (
	"context"
	"errors"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
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
	if response.Action != "rewrite" || response.Suggestion != "git status" || response.Source != "curated" || response.PackID != "core-git" || response.RuleID != "git-status-sttaus" {
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
