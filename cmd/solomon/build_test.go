package main

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

func TestReproducibleLocalBuild(t *testing.T) {
	first := filepath.Join(t.TempDir(), "solomon")
	second := filepath.Join(t.TempDir(), "solomon")
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
	if !bytes.Equal(firstData, secondData) || string(firstData) != "solomon dev\n" {
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
	output := filepath.Join(t.TempDir(), "solomon")
	command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-ldflags", "-X main.version=v1.2.3 -X main.commit=abc123", "-o", output, ".")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build injected metadata: %v\n%s", err, data)
	}
	data, err := exec.Command(output, "version").Output()
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "solomon v1.2.3 (abc123)\n" {
		t.Fatalf("version output = %q", data)
	}
}

func TestReleaseArtifactChecksumVerification(t *testing.T) {
	artifact := filepath.Join(t.TempDir(), "solomon-linux-amd64")
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
			output := filepath.Join(t.TempDir(), "solomon")
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
		"sigstore/cosign-installer@ba7bc0a3fef59531c69a25acd34668d6d3fe6f22",
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

func TestReleaseWorkflowAttestsPackagedArchive(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"attestations: write",
		"actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be",
		"id: release-archive",
		"subject-path: ${{ steps.release-archive.outputs.path }}",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks provenance marker %q", marker)
		}
	}
}

func TestReleaseWorkflowGeneratesCycloneDXSBOM(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"go install github.com/CycloneDX/cyclonedx-gomod/cmd/cyclonedx-gomod@v1.10.0",
		"scripts/release-sbom.sh",
		"name: sbom-",
		"path: dist/*.cdx.json",
		"if-no-files-found: error",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks CycloneDX SBOM marker %q", marker)
		}
	}
}

func TestReleaseWorkflowAuditsArtifactLicenses(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"go install github.com/google/go-licenses/v2@v2.0.1",
		"scripts/release-license-audit.sh",
		"name: license-audit-",
		"path: dist/*.licenses.csv",
		"if-no-files-found: error",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks license audit marker %q", marker)
		}
	}
}

func TestReleaseWorkflowSmokeTestsEveryArchive(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"smoke:",
		"needs: [build, compatibility]",
		"matrix: ${{ fromJSON(needs.compatibility.outputs.targets) }}",
		"actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0",
		"scripts/release-smoke-test.sh",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks smoke test marker %q", marker)
		}
	}
}

func TestReleaseWorkflowPublishesGitHubAssets(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"contents: write",
		"publish:",
		"needs: [build, smoke, bootstrap, verify]",
		"pattern: release-${{ github.ref_name }}-*",
		"bootstrap-${{ github.ref_name }}",
		"dist/install.sh dist/install.ps1",
		"cosign verify-blob dist/install.sh",
		"cosign verify-blob dist/install.ps1",
		"gh release create \"$GITHUB_REF_NAME\" --verify-tag --generate-notes",
		"dist/*.tar.gz dist/*.zip dist/*.sigstore.json dist/*.cdx.json dist/*.licenses.csv",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks GitHub asset publication marker %q", marker)
		}
	}
}

func TestReleaseWorkflowPublishesChecksumManifest(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"for artifact in solomon_*.tar.gz solomon_*.zip",
		"sha256sum \"$artifact\"",
		") > dist/checksums.txt",
		"test \"$(wc -l < dist/checksums.txt | tr -d ' ')\" -eq 5",
		"dist/checksums.txt",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks checksum manifest marker %q", marker)
		}
	}
}

func TestReleaseWorkflowGatesPublishingOnQualityChecks(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"verify:",
		"go-version: '1.26.6'",
		"go vet ./...",
		"go test -race -count=1 -timeout=2m ./...",
		"staticcheck ./...",
		"govulncheck ./...",
		"gosec ./...",
		"actionlint",
		"shellcheck scripts/*.sh",
		"needs: [compatibility, verify]",
		"needs: [build, smoke, bootstrap, verify]",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks quality gate marker %q", marker)
		}
	}
}

func TestWorkflowsUseSupportedPatchedGo(t *testing.T) {
	for _, name := range []string{"ci.yml", "release.yml", "release-dry-run.yml"} {
		workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", name))
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(workflow), "go-version-file:") || !strings.Contains(string(workflow), "go-version: '1.26.6'") {
			t.Fatalf("%s does not pin the supported Go toolchain", name)
		}
	}
}

func TestReleaseWorkflowValidatesCompatibilityMatrix(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"compatibility:",
		"cmd/release-compatibility",
		"outputs:",
		"targets: ${{ steps.matrix.outputs.targets }}",
		"needs: compatibility",
		"matrix: ${{ fromJSON(needs.compatibility.outputs.targets) }}",
		"needs: [build, compatibility]",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release workflow lacks compatibility matrix marker %q", marker)
		}
	}
}

func TestReleaseDryRunWorkflow(t *testing.T) {
	workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "release-dry-run.yml"))
	if err != nil {
		t.Fatal(err)
	}
	for _, marker := range []string{
		"workflow_dispatch:",
		"pull_request:",
		"RELEASE_VERSION: v0.0.0-dryrun.",
		"cmd/release-compatibility",
		"release-dry-run-",
		"scripts/release-sbom.sh",
		"scripts/release-license-audit.sh",
		"scripts/release-smoke-test.sh",
		"bootstrap:",
		"bootstrap-dry-run",
		"dist/install.sh",
	} {
		if !strings.Contains(string(workflow), marker) {
			t.Fatalf("release dry-run workflow lacks marker %q", marker)
		}
	}
	if strings.Contains(string(workflow), "cosign sign-blob") || strings.Contains(string(workflow), "TUF_") {
		t.Fatal("release dry-run workflow performs production signing")
	}
}

func TestReleaseWorkflowsDoNotPublishInactiveUpdateSurfaces(t *testing.T) {
	for _, name := range []string{"release.yml", "release-dry-run.yml"} {
		workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", name))
		if err != nil {
			t.Fatal(err)
		}
		for _, marker := range []string{"bundled-packs:", "update-manifest:", "release-pack-bundle.sh", "cmd/update-manifest"} {
			if strings.Contains(string(workflow), marker) {
				t.Fatalf("%s publishes inactive surface %q", name, marker)
			}
		}
	}
}

func TestWorkflowsPinActionsToFullCommitSHAs(t *testing.T) {
	reference := regexp.MustCompile(`(?m)^\s*-\s+uses:\s+[^@\s]+@([^\s#]+)`)
	sha := regexp.MustCompile(`^[0-9a-f]{40}$`)
	for _, name := range []string{"ci.yml", "release.yml", "release-dry-run.yml"} {
		workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", name))
		if err != nil {
			t.Fatal(err)
		}
		for _, match := range reference.FindAllStringSubmatch(string(workflow), -1) {
			if !sha.MatchString(match[1]) {
				t.Fatalf("%s has mutable action reference %q", name, match[1])
			}
		}
	}
}

func TestReleaseWorkflowsOmitTUFRegistry(t *testing.T) {
	for _, name := range []string{"release.yml", "release-dry-run.yml"} {
		workflow, err := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", name))
		if err != nil {
			t.Fatal(err)
		}
		for _, marker := range []string{"TUF_", "tuf-", "tuf-metadata"} {
			if strings.Contains(string(workflow), marker) {
				t.Fatalf("%s retains TUF registry marker %q", name, marker)
			}
		}
	}
	_, err := os.Stat(filepath.Join("..", "..", ".github", "workflows", "release-revocation.yml"))
	if !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("release revocation workflow exists: %v", err)
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
