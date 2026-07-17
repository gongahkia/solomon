package featuregate

import "testing"

func TestGatesFailClosed(t *testing.T) {
	tests := []struct {
		name     string
		gates    Gates
		registry bool
		update   bool
	}{
		{name: "default", gates: New(false, false)},
		{name: "registry only", gates: New(true, false), registry: true},
		{name: "update without registry", gates: New(false, true)},
		{name: "both", gates: New(true, true), registry: true, update: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := test.gates.Enabled(Registry); got != test.registry {
				t.Fatalf("registry = %t, want %t", got, test.registry)
			}
			if got := test.gates.Enabled(AutoUpdate); got != test.update {
				t.Fatalf("auto-update = %t, want %t", got, test.update)
			}
			if test.gates.Enabled("unknown") {
				t.Fatal("unknown gate must be disabled")
			}
		})
	}
}
