package daemon

import "testing"

func TestStateDirectoryUsesAbsoluteXDGPath(t *testing.T) {
	path, err := StateDirectory(func() (string, error) { return "/home/test", nil }, func(key string) string {
		if key == "XDG_STATE_HOME" {
			return "/state"
		}
		return ""
	})
	if err != nil || path != "/state/solomon" {
		t.Fatalf("StateDirectory() = %q, %v", path, err)
	}
}

func TestStateDirectoryFallsBackToAbsoluteHome(t *testing.T) {
	path, err := StateDirectory(func() (string, error) { return "/home/test", nil }, func(string) string { return "relative" })
	if err != nil || path != "/home/test/.local/state/solomon" {
		t.Fatalf("StateDirectory() = %q, %v", path, err)
	}
}
