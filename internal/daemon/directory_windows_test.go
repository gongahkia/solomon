//go:build windows

package daemon

import (
	"os/exec"
	"testing"
)

func TestPrepareDirectoryRejectsEveryoneWriteAccess(t *testing.T) {
	path := t.TempDir()
	output, err := exec.Command("icacls", path, "/grant", "*S-1-1-0:(OI)(CI)M").CombinedOutput()
	if err != nil {
		t.Fatalf("icacls: %v: %s", err, output)
	}
	if err := PrepareDirectory(path); err == nil {
		t.Fatal("PrepareDirectory() accepted Everyone modify access")
	}
}
