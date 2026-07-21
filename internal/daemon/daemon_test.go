//go:build !windows

package daemon

import (
	"context"
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/localstate"
	"github.com/gongahkia/close-enough/internal/packs"
)

func TestServerClientRoundTrip(t *testing.T) {
	endpoint, stop := startDaemonIntegration(t, func(_ context.Context, request Request) (Response, error) {
		return Response{Version: ProtocolVersion, Action: "hint", Suggestion: request.Command}, nil
	})
	response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "hint" || response.Suggestion != "git sttaus" {
		t.Fatalf("response = %+v", response)
	}
	stop()
	if _, err := os.Lstat(endpoint.Address); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("socket still exists: %v", err)
	}
}

func TestServerPersistsLearningPairs(t *testing.T) {
	store, err := localstate.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	service := &Service{Config: cfg, Store: store, Packs: resolver, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	endpoint, _ := startDaemonIntegration(t, service.Handle)
	client := Client{Endpoint: endpoint, Timeout: time.Second}
	for index := range localstate.DraftEvidenceThreshold {
		session := fmt.Sprintf("session-%d", index)
		if _, err := client.Request(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Session: session, Command: "mytool buid"}); err != nil {
			t.Fatal(err)
		}
		if _, err := client.Request(context.Background(), Request{Version: ProtocolVersion, Operation: PostSuccessOperation, Session: session, Command: "mytool build"}); err != nil {
			t.Fatal(err)
		}
	}
	drafts, err := store.ListReviewableDrafts(context.Background())
	if err != nil || len(drafts) != 1 || drafts[0].EvidenceCount != localstate.DraftEvidenceThreshold {
		t.Fatalf("drafts = %#v, %v", drafts, err)
	}
}
