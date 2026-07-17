package shell

import (
	"strings"
	"testing"
)

func TestScriptsExistForSupportedShells(t *testing.T) {
	for _, name := range []string{"zsh", "bash", "fish", "powershell"} {
		script, err := Script(name)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if !strings.Contains(script, "close-enough") {
			t.Fatalf("%s script lacks binary invocation", name)
		}
		versionMarker := "version"
		if name == "fish" {
			versionMarker = "fields[1]"
		}
		if !strings.Contains(script, versionMarker) {
			t.Fatalf("%s script lacks protocol-version validation", name)
		}
	}
}

func TestDoctorReportsTiers(t *testing.T) {
	if got := Doctor("/bin/zsh", "darwin"); !got.Supported || got.Tier != "first-class" {
		t.Fatalf("unexpected zsh doctor result: %#v", got)
	}
	if got := Doctor("pwsh", "windows"); !got.Supported || got.Tier != "tiered" {
		t.Fatalf("unexpected powershell doctor result: %#v", got)
	}
}
