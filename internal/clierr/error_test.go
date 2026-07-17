package clierr

import (
	"errors"
	"fmt"
	"testing"
)

func TestCodeIsStable(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{name: "success", want: ExitSuccess},
		{name: "usage", err: New(Usage, "bad argument"), want: ExitUsage},
		{name: "configuration", err: New(Configuration, "bad config"), want: ExitConfiguration},
		{name: "input", err: New(Input, "bad input"), want: ExitInput},
		{name: "operation", err: New(Operation, "write failed"), want: ExitOperation},
		{name: "wrapped", err: fmt.Errorf("context: %w", New(Input, "bad input")), want: ExitInput},
		{name: "untyped", err: errors.New("unexpected"), want: ExitInternal},
		{name: "unknown kind", err: New(Internal, "unexpected"), want: ExitInternal},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := Code(test.err); got != test.want {
				t.Fatalf("Code(%v) = %d, want %d", test.err, got, test.want)
			}
		})
	}
}

func TestWrapNil(t *testing.T) {
	if err := Wrap(Operation, nil); err != nil {
		t.Fatalf("Wrap(nil) = %v", err)
	}
}
