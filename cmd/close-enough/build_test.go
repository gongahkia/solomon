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

func TestReleaseBuildMatrixTargets(t *testing.T) {
	for _, target := range []struct{ goos, goarch string }{
		{goos: "linux", goarch: "amd64"},
		{goos: "linux", goarch: "arm64"},
		{goos: "darwin", goarch: "amd64"},
		{goos: "darwin", goarch: "arm64"},
		{goos: "windows", goarch: "amd64"},
	} {
		t.Run(target.goos+"-"+target.goarch, func(t *testing.T) {
			output := filepath.Join(t.TempDir(), "close-enough")
			command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-ldflags", "-X main.version=v1.2.3 -X main.commit=abc123", "-o", output, ".")
			command.Env = replaceHarnessEnvironment(replaceHarnessEnvironment(replaceHarnessEnvironment(os.Environ(), "GOOS", target.goos), "GOARCH", target.goarch), "CGO_ENABLED", "0")
			if data, err := command.CombinedOutput(); err != nil {
				t.Fatalf("release build: %v\n%s", err, data)
			}
			info, err := os.Stat(output)
			if err != nil || info.Size() == 0 {
				t.Fatalf("release artifact = %#v, %v", info, err)
			}
		})
	}
}

func TestReleaseBuildMatrixRejectsUnsupportedTarget(t *testing.T) {
	command := exec.Command("go", "build", "-mod=readonly", ".")
	command.Env = replaceHarnessEnvironment(replaceHarnessEnvironment(os.Environ(), "GOOS", "unsupported"), "GOARCH", "amd64")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("unsupported release target built successfully: %s", data)
	}
}

func TestReleaseWorkflowConfiguresKeylessSigning(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"id-token: write",
		"sigstore/cosign-installer@v4.1.0",
		"cosign sign-blob --yes --bundle",
		`test -n "$archive"`,
		`test -s "$archive.sigstore.json"`,
		"name: sigstore-bundle-",
		"path: dist/*.sigstore.json",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks keyless signing marker %q", marker)
		}
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
