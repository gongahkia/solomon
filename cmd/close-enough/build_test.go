package main

import (
	"bytes"
	"crypto/sha256"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestReproducibleLocalBuild(t *testing.T) {
	first := filepath.Join(t.TempDir(), "close-enough")
	second := filepath.Join(t.TempDir(), "close-enough")
	for _, output := range []string{first, second} {
		command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", output, ".")
		if data, err := command.CombinedOutput(); err != nil {
			t.Fatalf("build %q: %v\n%s", output, err, data)
		}
	}
	firstBinary, err := os.ReadFile(first)
	if err != nil {
		t.Fatal(err)
	}
	secondBinary, err := os.ReadFile(second)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstBinary, secondBinary) {
		t.Fatal("build outputs differ")
	}
	firstData, err := exec.Command(first, "version").Output()
	if err != nil {
		t.Fatal(err)
	}
	secondData, err := exec.Command(second, "version").Output()
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstData, secondData) || string(firstData) != "close-enough dev\n" {
		t.Fatalf("unexpected version output: %q, %q", firstData, secondData)
	}
}

func TestLocalBuildRejectsMissingPackage(t *testing.T) {
	command := exec.Command("go", "build", "-mod=readonly", "./missing-package")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("missing package built successfully: %s", data)
	}
}

func TestBuildInjectsVersionAndCommit(t *testing.T) {
	output := filepath.Join(t.TempDir(), "close-enough")
	command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-ldflags", "-X main.version=v1.2.3 -X main.commit=abc123", "-o", output, ".")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build injected metadata: %v\n%s", err, data)
	}
	data, err := exec.Command(output, "version").Output()
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "close-enough v1.2.3 (abc123)\n" {
		t.Fatalf("version output = %q", data)
	}
}

func TestReleaseArtifactChecksumVerification(t *testing.T) {
	artifact := filepath.Join(t.TempDir(), "close-enough-linux-amd64")
	command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-ldflags", "-X main.version=v1.2.3 -X main.commit=abc123", "-o", artifact, ".")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build release artifact: %v\n%s", err, data)
	}
	binary, err := os.ReadFile(artifact)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(binary)
	manifest := fmt.Sprintf("%x  %s\n", digest, filepath.Base(artifact))
	if !verifyReleaseArtifactChecksum(binary, artifact, manifest) {
		t.Fatalf("release artifact failed checksum verification: %q", manifest)
	}
	tampered := append([]byte(nil), binary...)
	tampered[0] ^= 1
	if verifyReleaseArtifactChecksum(tampered, artifact, manifest) {
		t.Fatal("tampered release artifact passed checksum verification")
	}
}

func verifyReleaseArtifactChecksum(data []byte, artifact, manifest string) bool {
	fields := strings.Fields(manifest)
	if len(fields) != 2 || fields[1] != filepath.Base(artifact) {
		return false
	}
	digest := sha256.Sum256(data)
	return fields[0] == fmt.Sprintf("%x", digest)
}
