package daemon

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
)

func TestDaemonEventContractRedactsRequestSecrets(t *testing.T) {
	directory := t.TempDir()
	if err := os.WriteFile(filepath.Join(directory, "git"), []byte("#!/bin/sh\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	cfg := config.Default()
	service := Service{Config: cfg, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: directory, CWD: directory})}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "gti --token=super-secret"})
	if err != nil {
		t.Fatal(err)
	}
	if err := response.Validate(); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(response)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"super-secret", `"command"`, `"failure_output"`, `"session"`, `"token"`} {
		if strings.Contains(string(data), forbidden) {
			t.Fatalf("daemon event leaked %q: %s", forbidden, data)
		}
	}
	var event map[string]json.RawMessage
	if err := json.Unmarshal(data, &event); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"version", "action", "suggestion", "explanation", "confidence", "risk", "source"} {
		if _, ok := event[field]; !ok {
			t.Fatalf("daemon event omitted %q: %s", field, data)
		}
	}
	if response.Suggestion != "git --token=[REDACTED]" || response.Action == "rewrite" || response.Risk != "high" || response.Source != "heuristic" {
		t.Fatalf("redacted daemon response = %#v", response)
	}
}
