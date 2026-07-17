package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReleaseSBOMScript(t *testing.T) {
	directory := t.TempDir()
	module := filepath.Join(directory, "module")
	if err := os.Mkdir(module, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(module, "go.mod"), []byte("module example.com/test\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	check := filepath.Join(directory, "check")
	generator := writeSBOMGenerator(t, directory, "printf '%s/%s/%s' \"$GOOS\" \"$GOARCH\" \"$CGO_ENABLED\" > \"$CHECK_FILE\"\nprintf '{\"bomFormat\":\"CycloneDX\"}\\n' > \"$4\"")
	output := filepath.Join(directory, "release.cdx.json")
	command := exec.Command("sh", "../../scripts/release-sbom.sh", generator, module, output, "linux", "arm64")
	command.Env = append(os.Environ(), "CHECK_FILE="+check)
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("generate SBOM: %v\n%s", err, data)
	}
	if data, err := os.ReadFile(output); err != nil || string(data) != "{\"bomFormat\":\"CycloneDX\"}\n" {
		t.Fatalf("SBOM = %q, %v", data, err)
	}
	if data, err := os.ReadFile(check); err != nil || string(data) != "linux/arm64/0" {
		t.Fatalf("generator build constraints = %q, %v", data, err)
	}
}

func TestReleaseSBOMScriptRejectsGeneratorFailure(t *testing.T) {
	directory := t.TempDir()
	module := filepath.Join(directory, "module")
	if err := os.Mkdir(module, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(module, "go.mod"), []byte("module example.com/test\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	generator := writeSBOMGenerator(t, directory, "exit 9")
	command := exec.Command("sh", "../../scripts/release-sbom.sh", generator, module, filepath.Join(directory, "release.cdx.json"), "linux", "amd64")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("failed generator produced an SBOM: %s", data)
	}
}

func writeSBOMGenerator(t *testing.T, directory, body string) string {
	t.Helper()
	generator := filepath.Join(directory, "cyclonedx-gomod")
	if err := os.WriteFile(generator, []byte("#!/bin/sh\nset -eu\n[ \"$1\" = app ]\n[ \"$2\" = -json ]\n[ \"$3\" = -output ]\n"+body+"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	return generator
}
