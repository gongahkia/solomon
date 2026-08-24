//go:build !windows

package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestUnixInstallerDownloadsAndVerifiesReleaseAssets(t *testing.T) {
	version := "v1.2.3"
	releaseDirectory := t.TempDir()
	archive := writeUnixInstallerRelease(t, releaseDirectory, version)
	server := httptest.NewServer(http.FileServer(http.Dir(releaseDirectory)))
	defer server.Close()
	fakeDirectory := t.TempDir()
	log := filepath.Join(t.TempDir(), "cosign.log")
	writeFakeCosign(t, fakeDirectory)
	installDirectory := filepath.Join(t.TempDir(), "bin")
	rc := filepath.Join(t.TempDir(), "zshrc")
	environment := installerEnvironment(server.URL, version, fakeDirectory, installDirectory, rc, log)
	runUnixInstaller(t, environment)
	target := filepath.Join(installDirectory, "close-enough")
	data, err := exec.Command(target, "version").Output()
	if err != nil || string(data) != "close-enough dev\n" {
		t.Fatalf("installed binary version = %q, %v", data, err)
	}
	initialization, err := os.ReadFile(rc)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(string(initialization), "# >>> close-enough initialize >>>") != 1 || strings.Count(string(initialization), "# <<< close-enough initialize <<<") != 1 {
		t.Fatalf("shell initialization = %q", initialization)
	}
	verification, err := os.ReadFile(log)
	if err != nil || !strings.Contains(string(verification), archive) || !strings.Contains(string(verification), "--certificate-identity") || !strings.Contains(string(verification), "refs/tags/"+version) {
		t.Fatalf("cosign invocation = %q, %v", verification, err)
	}
	runUnixInstaller(t, environment)
	initialization, err = os.ReadFile(rc)
	if err != nil || strings.Count(string(initialization), "# >>> close-enough initialize >>>") != 1 {
		t.Fatalf("idempotent initialization = %q, %v", initialization, err)
	}
	runUnixInstaller(t, environment, "--uninstall")
	if _, err := os.Lstat(target); !os.IsNotExist(err) {
		t.Fatalf("installed binary remains after uninstall: %v", err)
	}
	initialization, err = os.ReadFile(rc)
	if err != nil || strings.Contains(string(initialization), "close-enough initialize") {
		t.Fatalf("shell initialization remains after uninstall = %q, %v", initialization, err)
	}
}

func TestUnixInstallerRemovesLegacyBashInitialization(t *testing.T) {
	version := "v1.2.3"
	releaseDirectory := t.TempDir()
	writeUnixInstallerRelease(t, releaseDirectory, version)
	server := httptest.NewServer(http.FileServer(http.Dir(releaseDirectory)))
	defer server.Close()
	fakeDirectory := t.TempDir()
	writeFakeCosign(t, fakeDirectory)
	home := t.TempDir()
	legacy := filepath.Join(home, ".bashrc")
	legacyBlock := "# before\n# >>> close-enough initialize >>>\neval \"$(close-enough init --shell bash)\"\n# <<< close-enough initialize <<<\n# after\n"
	if err := os.WriteFile(legacy, []byte(legacyBlock), 0o600); err != nil {
		t.Fatal(err)
	}
	environment := installerEnvironment(server.URL, version, fakeDirectory, filepath.Join(t.TempDir(), "bin"), filepath.Join(home, ".zshrc"), filepath.Join(t.TempDir(), "cosign.log"))
	environment = replaceHarnessEnvironment(environment, "HOME", home)
	runUnixInstaller(t, environment)
	data, err := os.ReadFile(legacy)
	if err != nil || strings.Contains(string(data), "close-enough initialize") || !strings.Contains(string(data), "# before") || !strings.Contains(string(data), "# after") {
		t.Fatalf("legacy Bash initialization = %q, %v", data, err)
	}
}

func TestUnixInstallerRejectsChecksumAndSignatureFailures(t *testing.T) {
	version := "v1.2.3"
	releaseDirectory := t.TempDir()
	writeUnixInstallerRelease(t, releaseDirectory, version)
	server := httptest.NewServer(http.FileServer(http.Dir(releaseDirectory)))
	defer server.Close()
	fakeDirectory := t.TempDir()
	writeFakeCosign(t, fakeDirectory)
	log := filepath.Join(t.TempDir(), "cosign.log")
	environment := installerEnvironment(server.URL, version, fakeDirectory, filepath.Join(t.TempDir(), "bin"), filepath.Join(t.TempDir(), "bashrc"), log)
	if err := os.WriteFile(filepath.Join(releaseDirectory, "checksums.txt"), []byte(strings.Repeat("0", 64)+"  "+installerArchiveName(version)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if data, err := runUnixInstallerOutput(environment); err == nil || !strings.Contains(string(data), "checksum mismatch") {
		t.Fatalf("checksum failure = %v\n%s", err, data)
	}
	if _, err := os.Lstat(filepath.Join(environmentValue(environment, "CLOSE_ENOUGH_INSTALL_DIR"), "close-enough")); !os.IsNotExist(err) {
		t.Fatalf("checksum failure installed a binary: %v", err)
	}
	writeUnixInstallerRelease(t, releaseDirectory, version)
	environment = replaceHarnessEnvironment(environment, "CLOSE_ENOUGH_TEST_COSIGN_FAIL", "1")
	if data, err := runUnixInstallerOutput(environment); err == nil || !strings.Contains(string(data), "Sigstore") {
		t.Fatalf("signature failure = %v\n%s", err, data)
	}
}

func TestInstallerScriptsVerifyArtifactsWithoutRegisteringServices(t *testing.T) {
	for _, test := range []struct {
		script          string
		uninstallMarker string
	}{
		{script: "../../scripts/install.sh", uninstallMarker: "--uninstall"},
		{script: "../../scripts/install.ps1", uninstallMarker: "$Uninstall"},
	} {
		data, err := os.ReadFile(test.script)
		if err != nil {
			t.Fatal(err)
		}
		text := string(data)
		for _, marker := range []string{"checksums.txt", "verify-blob", "certificate-identity", test.uninstallMarker} {
			if !strings.Contains(text, marker) {
				t.Fatalf("%s lacks %q", test.script, marker)
			}
		}
		for _, forbidden := range []string{"systemctl", "launchctl", "schtasks", "New-Service", "sc create"} {
			if strings.Contains(strings.ToLower(text), strings.ToLower(forbidden)) {
				t.Fatalf("%s registers a service through %q", test.script, forbidden)
			}
		}
	}
}

func writeUnixInstallerRelease(t *testing.T, directory, version string) string {
	t.Helper()
	binary := filepath.Join(t.TempDir(), "close-enough")
	command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", binary, ".")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build installer fixture: %v\n%s", err, data)
	}
	archive := installerArchiveName(version)
	path := filepath.Join(directory, archive)
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	compressed := gzip.NewWriter(file)
	writer := tar.NewWriter(compressed)
	root := strings.TrimSuffix(archive, ".tar.gz")
	if err := writer.WriteHeader(&tar.Header{Name: root + "/", Mode: 0o755, Typeflag: tar.TypeDir}); err != nil {
		t.Fatal(err)
	}
	input, err := os.Open(binary)
	if err != nil {
		t.Fatal(err)
	}
	info, err := input.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if err := writer.WriteHeader(&tar.Header{Name: root + "/close-enough", Mode: 0o755, Size: info.Size(), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(writer, input); err != nil {
		t.Fatal(err)
	}
	if err := input.Close(); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := compressed.Close(); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(contents)
	if err := os.WriteFile(filepath.Join(directory, "checksums.txt"), []byte(fmt.Sprintf("%x  %s\n", digest, archive)), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, archive+".sigstore.json"), []byte("{}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return archive
}

func installerArchiveName(version string) string {
	return "close-enough_" + version + "_" + runtime.GOOS + "_" + runtime.GOARCH + ".tar.gz"
}

func writeFakeCosign(t *testing.T, directory string) {
	t.Helper()
	path := filepath.Join(directory, "cosign")
	script := `#!/bin/sh
set -eu
[ "$1" = verify-blob ]
[ -f "$2" ]
[ "$3" = --bundle ]
[ -f "$4" ]
[ "$5" = --certificate-identity ]
case "$6" in
  https://github.com/gongahkia/close-enough/.github/workflows/release.yml@refs/tags/v*) ;;
  *) exit 1 ;;
esac
[ "${CLOSE_ENOUGH_TEST_COSIGN_FAIL:-}" != 1 ] || exit 1
printf '%s\n' "$@" > "$CLOSE_ENOUGH_TEST_COSIGN_LOG"
`
	if err := os.WriteFile(path, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
}

func installerEnvironment(releaseBaseURL, version, fakeDirectory, installDirectory, rc, log string) []string {
	environment := replaceHarnessEnvironment(os.Environ(), "CLOSE_ENOUGH_VERSION", version)
	environment = replaceHarnessEnvironment(environment, "CLOSE_ENOUGH_RELEASE_BASE_URL", releaseBaseURL)
	environment = replaceHarnessEnvironment(environment, "CLOSE_ENOUGH_INSTALL_DIR", installDirectory)
	environment = replaceHarnessEnvironment(environment, "CLOSE_ENOUGH_SHELL", "zsh")
	environment = replaceHarnessEnvironment(environment, "CLOSE_ENOUGH_SHELL_RC", rc)
	environment = replaceHarnessEnvironment(environment, "CLOSE_ENOUGH_TEST_COSIGN_LOG", log)
	return replaceHarnessEnvironment(environment, "PATH", fakeDirectory+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func runUnixInstaller(t *testing.T, environment []string, arguments ...string) {
	t.Helper()
	if data, err := runUnixInstallerOutput(environment, arguments...); err != nil {
		t.Fatalf("run installer: %v\n%s", err, data)
	}
}

func runUnixInstallerOutput(environment []string, arguments ...string) ([]byte, error) {
	command := exec.Command("sh", append([]string{"../../scripts/install.sh"}, arguments...)...)
	command.Env = environment
	return command.CombinedOutput()
}

func environmentValue(environment []string, key string) string {
	prefix := key + "="
	for _, value := range environment {
		if strings.HasPrefix(value, prefix) {
			return strings.TrimPrefix(value, prefix)
		}
	}
	return ""
}
