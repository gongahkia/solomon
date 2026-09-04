package main

import (
	"os/exec"
	"testing"
)

func TestReleaseNameScript(t *testing.T) {
	for _, test := range []struct {
		version, goos, goarch, extension, want string
	}{
		{version: "v1.2.3", goos: "linux", goarch: "amd64", extension: "tar.gz", want: "solomon_v1.2.3_linux_amd64.tar.gz\n"},
		{version: "v1.2.3-rc.1+build.7", goos: "darwin", goarch: "arm64", extension: "tar.gz", want: "solomon_v1.2.3-rc.1+build.7_darwin_arm64.tar.gz\n"},
		{version: "v1.2.3", goos: "windows", goarch: "amd64", extension: "zip", want: "solomon_v1.2.3_windows_amd64.zip\n"},
	} {
		t.Run(test.goos+"-"+test.goarch, func(t *testing.T) {
			command := exec.Command("sh", "../../scripts/release-name.sh", test.version, test.goos, test.goarch, test.extension)
			data, err := command.Output()
			if err != nil || string(data) != test.want {
				t.Fatalf("release name = %q, %v; want %q", data, err, test.want)
			}
		})
	}
}

func TestReleaseNameScriptRejectsInvalidInput(t *testing.T) {
	command := exec.Command("sh", "../../scripts/release-name.sh", "v1.2.3/escape", "linux", "amd64", "tar.gz")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("invalid release name succeeded: %s", data)
	}
}
