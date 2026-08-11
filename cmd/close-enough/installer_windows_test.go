//go:build windows

package main

import (
	"archive/zip"
	"crypto/sha256"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestWindowsInstallerVerifiesArtifactsAndManagesShellInitialization(t *testing.T) {
	pwsh, err := exec.LookPath("pwsh")
	if err != nil {
		t.Skip("pwsh is unavailable")
	}
	version := "v1.2.3"
	releaseDirectory := t.TempDir()
	archive := writeWindowsInstallerRelease(t, releaseDirectory, version)
	server := httptest.NewServer(http.FileServer(http.Dir(releaseDirectory)))
	defer server.Close()
	fakeDirectory := t.TempDir()
	if err := os.WriteFile(filepath.Join(fakeDirectory, "cosign.cmd"), []byte("@echo off\r\nif not \"%1\"==\"verify-blob\" exit /b 1\r\nif not exist \"%2\" exit /b 1\r\nexit /b 0\r\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	installDirectory := filepath.Join(t.TempDir(), "bin")
	profile := filepath.Join(t.TempDir(), "profile.ps1")
	environment := replaceHarnessEnvironment(os.Environ(), "PATH", fakeDirectory+string(os.PathListSeparator)+os.Getenv("PATH"))
	runWindowsInstaller(t, pwsh, environment, "-Version", version, "-ReleaseBaseUrl", server.URL, "-InstallDir", installDirectory, "-Shell", "powershell", "-ShellProfile", profile)
	target := filepath.Join(installDirectory, "close-enough.exe")
	data, err := exec.Command(target, "version").Output()
	if err != nil || strings.TrimSpace(string(data)) != "close-enough dev" {
		t.Fatalf("installed binary version = %q, %v", data, err)
	}
	initialization, err := os.ReadFile(profile)
	if err != nil || strings.Count(string(initialization), "# >>> close-enough initialize >>>") != 1 || !strings.Contains(string(initialization), target) {
		t.Fatalf("shell initialization = %q, %v", initialization, err)
	}
	runWindowsInstaller(t, pwsh, environment, "-Version", version, "-ReleaseBaseUrl", server.URL, "-InstallDir", installDirectory, "-Shell", "powershell", "-ShellProfile", profile)
	initialization, err = os.ReadFile(profile)
	if err != nil || strings.Count(string(initialization), "# >>> close-enough initialize >>>") != 1 {
		t.Fatalf("idempotent initialization = %q, %v", initialization, err)
	}
	runWindowsInstaller(t, pwsh, environment, "-Uninstall", "-InstallDir", installDirectory, "-Shell", "powershell", "-ShellProfile", profile)
	if _, err := os.Lstat(target); !os.IsNotExist(err) {
		t.Fatalf("installed binary remains after uninstall: %v", err)
	}
	initialization, err = os.ReadFile(profile)
	if err != nil || strings.Contains(string(initialization), "close-enough initialize") {
		t.Fatalf("shell initialization remains after uninstall = %q, %v", initialization, err)
	}
	if _, err := os.Stat(filepath.Join(releaseDirectory, archive)); err != nil {
		t.Fatal(err)
	}
}

func writeWindowsInstallerRelease(t *testing.T, directory, version string) string {
	t.Helper()
	binary := filepath.Join(t.TempDir(), "close-enough.exe")
	command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", binary, ".")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build installer fixture: %v\n%s", err, data)
	}
	archive := "close-enough_" + version + "_windows_amd64.zip"
	path := filepath.Join(directory, archive)
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	writer := zip.NewWriter(file)
	entry, err := writer.Create(strings.TrimSuffix(archive, ".zip") + "/close-enough.exe")
	if err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(binary)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := entry.Write(contents); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	contents, err = os.ReadFile(path)
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

func runWindowsInstaller(t *testing.T, pwsh string, environment []string, arguments ...string) {
	t.Helper()
	command := exec.Command(pwsh, append([]string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "../../scripts/install.ps1"}, arguments...)...)
	command.Env = environment
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("run installer: %v\n%s", err, data)
	}
}
