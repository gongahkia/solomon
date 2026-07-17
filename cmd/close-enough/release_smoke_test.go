package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReleaseSmokeTestScript(t *testing.T) {
	for _, target := range []struct {
		goos, goarch, extension string
	}{
		{goos: "linux", goarch: "amd64", extension: "tar.gz"},
		{goos: "windows", goarch: "amd64", extension: "zip"},
	} {
		t.Run(target.goos, func(t *testing.T) {
			directory := t.TempDir()
			binary := filepath.Join(directory, "close-enough")
			if err := os.WriteFile(binary, []byte("#!/bin/sh\nprintf 'close-enough v1.2.3 (0123456789012345678901234567890123456789)\\n'\n"), 0o700); err != nil {
				t.Fatal(err)
			}
			root := "close-enough_v1.2.3_" + target.goos + "_" + target.goarch
			archive := filepath.Join(directory, root+"."+target.extension)
			archiveScript := "../../scripts/release-archive.sh"
			if target.extension == "zip" {
				archiveScript = "../../scripts/release-zip.sh"
			}
			if data, err := exec.Command("sh", archiveScript, binary, archive, root).CombinedOutput(); err != nil {
				t.Fatalf("create release archive: %v\n%s", err, data)
			}
			if data, err := exec.Command("sh", "../../scripts/release-smoke-test.sh", archive, target.goos, target.goarch, "v1.2.3").CombinedOutput(); err != nil {
				t.Fatalf("smoke release archive: %v\n%s", err, data)
			}
		})
	}
}

func TestReleaseSmokeTestScriptRejectsUnexpectedArchiveContents(t *testing.T) {
	directory := t.TempDir()
	root := filepath.Join(directory, "close-enough_v1.2.3_linux_amd64")
	if err := os.Mkdir(root, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "close-enough"), []byte("#!/bin/sh\nprintf 'close-enough v1.2.3 (0123456789012345678901234567890123456789)\\n'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "unexpected"), []byte("unexpected"), 0o600); err != nil {
		t.Fatal(err)
	}
	archive := filepath.Join(directory, "close-enough_v1.2.3_linux_amd64.tar.gz")
	if data, err := exec.Command("tar", "-C", directory, "-czf", archive, filepath.Base(root)).CombinedOutput(); err != nil {
		t.Fatalf("create invalid release archive: %v\n%s", err, data)
	}
	if data, err := exec.Command("sh", "../../scripts/release-smoke-test.sh", archive, "linux", "amd64", "v1.2.3").CombinedOutput(); err == nil {
		t.Fatalf("unexpected archive contents passed smoke test: %s", data)
	}
}
