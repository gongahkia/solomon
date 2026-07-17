package main

import (
	"archive/tar"
	"compress/gzip"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReleaseArchiveScript(t *testing.T) {
	directory := t.TempDir()
	binary := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(binary, []byte("binary"), 0o700); err != nil {
		t.Fatal(err)
	}
	archive := filepath.Join(directory, "close-enough-linux-amd64.tar.gz")
	command := exec.Command("sh", "../../scripts/release-archive.sh", binary, archive, "close-enough-linux-amd64")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("create release archive: %v\n%s", err, data)
	}
	file, err := os.Open(archive)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	compressed, err := gzip.NewReader(file)
	if err != nil {
		t.Fatal(err)
	}
	defer compressed.Close()
	reader := tar.NewReader(compressed)
	for {
		header, err := reader.Next()
		if err == io.EOF {
			t.Fatal("release binary is missing from archive")
		}
		if err != nil {
			t.Fatal(err)
		}
		if header.Name != "close-enough-linux-amd64/close-enough" {
			continue
		}
		data, err := io.ReadAll(reader)
		if err != nil || string(data) != "binary" {
			t.Fatalf("archive payload = %q, %v", data, err)
		}
		break
	}
}

func TestReleaseArchiveScriptRejectsMissingBinary(t *testing.T) {
	command := exec.Command("sh", "../../scripts/release-archive.sh", filepath.Join(t.TempDir(), "missing"), filepath.Join(t.TempDir(), "release.tar.gz"), "close-enough-linux-amd64")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("missing binary archived successfully: %s", data)
	}
}
