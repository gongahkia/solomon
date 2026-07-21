package daemon

import (
	"context"
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
