package main

import (
	"archive/zip"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReleaseZIPScript(t *testing.T) {
	directory := t.TempDir()
	binary := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(binary, []byte("binary"), 0o700); err != nil {
		t.Fatal(err)
	}
	archive := filepath.Join(directory, "close-enough-windows-amd64.zip")
	command := exec.Command("sh", "../../scripts/release-zip.sh", binary, archive, "close-enough-windows-amd64")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("create release ZIP: %v\n%s", err, data)
	}
	reader, err := zip.OpenReader(archive)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	for _, file := range reader.File {
		if file.Name != "close-enough-windows-amd64/close-enough.exe" {
			continue
		}
		content, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(content)
		content.Close()
		if err != nil || string(data) != "binary" {
			t.Fatalf("ZIP payload = %q, %v", data, err)
		}
		return
	}
	t.Fatal("release binary is missing from ZIP")
}

func TestReleaseZIPScriptRejectsMissingBinary(t *testing.T) {
	command := exec.Command("sh", "../../scripts/release-zip.sh", filepath.Join(t.TempDir(), "missing"), filepath.Join(t.TempDir(), "release.zip"), "close-enough-windows-amd64")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("missing binary archived successfully: %s", data)
	}
}
