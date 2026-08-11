package main

import (
	"slices"
	"testing"
	"time"
)

func TestPercentileUsesNearestRank(t *testing.T) {
	samples := []time.Duration{5, 1, 4, 2, 3}
	slices.Sort(samples)
	for value, want := range map[int]time.Duration{50: 3, 95: 5, 99: 5, 100: 5} {
		if got := percentile(samples, value); got != want {
			t.Fatalf("percentile(%d) = %s, want %s", value, got, want)
		}
	}
	if percentile(samples, 0) != 0 || percentile(nil, 50) != 0 {
		t.Fatal("invalid percentile input produced a value")
	}
}
