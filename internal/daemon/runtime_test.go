package daemon

import "testing"

func TestRuntimeDirectoryUsesAbsoluteXDGPath(t *testing.T) {
	path, err := RuntimeDirectory(func() (string, error) { return "/home/test", nil }, func(key string) string {
		if key == "XDG_RUNTIME_DIR" {
			return "/run/user/1000"
		}
		return ""
	})
	if err != nil || path != "/run/user/1000/close-enough" {
		t.Fatalf("RuntimeDirectory() = %q, %v", path, err)
	}
}

func TestRuntimeDirectoryRejectsRelativeHome(t *testing.T) {
	_, err := RuntimeDirectory(func() (string, error) { return "relative", nil }, func(string) string { return "" })
	if err == nil {
		t.Fatal("RuntimeDirectory() succeeded")
	}
}
