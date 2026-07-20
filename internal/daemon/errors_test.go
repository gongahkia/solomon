package daemon

import "testing"

func TestLifecycleErrorsAreDistinct(t *testing.T) {
	seen := map[error]struct{}{}
	for _, err := range []error{ErrUnavailable, ErrAlreadyRunning, ErrNotRunning, ErrStaleEndpoint} {
		if err == nil {
			t.Fatal("lifecycle error is nil")
		}
		if _, exists := seen[err]; exists {
			t.Fatalf("duplicate lifecycle error %q", err)
		}
		seen[err] = struct{}{}
	}
}
