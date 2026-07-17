package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReleaseLicenseAuditScript(t *testing.T) {
	directory := t.TempDir()
	module := filepath.Join(directory, "module")
	if err := os.MkdirAll(filepath.Join(module, "cmd", "close-enough"), 0o700); err != nil {
		t.Fatal(err)
	}
	check := filepath.Join(directory, "check")
	auditor := writeLicenseAuditor(t, directory, "case \"$1\" in\n  check) printf '%s/%s/%s' \"$GOOS\" \"$GOARCH\" \"$CGO_ENABLED\" > \"$CHECK_FILE\" ;;\n  report) printf 'example.com/library,https://example.com/LICENSE,MIT\\n' ;;\n  *) exit 9 ;;\nesac")
	output := filepath.Join(directory, "release.licenses.csv")
	command := exec.Command("sh", "../../scripts/release-license-audit.sh", auditor, module, output, "windows", "amd64")
	command.Env = append(os.Environ(), "CHECK_FILE="+check)
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("audit release licenses: %v\n%s", err, data)
	}
	if data, err := os.ReadFile(output); err != nil || string(data) != "example.com/library,https://example.com/LICENSE,MIT\n" {
		t.Fatalf("license audit = %q, %v", data, err)
	}
	if data, err := os.ReadFile(check); err != nil || string(data) != "windows/amd64/0" {
		t.Fatalf("auditor build constraints = %q, %v", data, err)
	}
}

func TestReleaseLicenseAuditScriptRejectsFailedCheck(t *testing.T) {
	directory := t.TempDir()
	module := filepath.Join(directory, "module")
	if err := os.MkdirAll(filepath.Join(module, "cmd", "close-enough"), 0o700); err != nil {
		t.Fatal(err)
	}
	auditor := writeLicenseAuditor(t, directory, "exit 9")
	command := exec.Command("sh", "../../scripts/release-license-audit.sh", auditor, module, filepath.Join(directory, "release.licenses.csv"), "linux", "amd64")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("failed license check completed: %s", data)
	}
}

func writeLicenseAuditor(t *testing.T, directory, body string) string {
	t.Helper()
	auditor := filepath.Join(directory, "go-licenses")
	if err := os.WriteFile(auditor, []byte("#!/bin/sh\nset -eu\n"+body+"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	return auditor
}
