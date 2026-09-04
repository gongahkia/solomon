package main

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"time"

	"github.com/gongahkia/solomon/internal/config"
	"github.com/gongahkia/solomon/internal/diagnose"
)

const (
	sampleCount = 200
	p50Limit    = 20 * time.Millisecond
	p95Limit    = 50 * time.Millisecond
	p99Limit    = 100 * time.Millisecond
)

func main() {
	directory, err := os.MkdirTemp("", "solomon-latency-")
	if err != nil {
		fail(err)
	}
	defer os.RemoveAll(directory)
	// #nosec G306 -- The latency fixture must be executable, and its temporary directory is private.
	if err := os.WriteFile(filepath.Join(directory, "git"), []byte("#!/bin/sh\n"), 0o700); err != nil {
		fail(err)
	}
	engine := diagnose.New(diagnose.Options{Config: config.Default(), Path: directory, CWD: directory, Cache: diagnose.NewCache()})
	if decision, err := engine.Check("gti status", "pre"); err != nil || decision.Action != "hint" {
		fail(fmt.Errorf("latency-gate setup = %#v, %v", decision, err))
	}
	samples := make([]time.Duration, 0, sampleCount)
	for range sampleCount {
		started := time.Now()
		if _, err := engine.Check("gti status", "pre"); err != nil {
			fail(err)
		}
		samples = append(samples, time.Since(started))
	}
	slices.Sort(samples)
	values := map[string]time.Duration{"p50": percentile(samples, 50), "p95": percentile(samples, 95), "p99": percentile(samples, 99)}
	for name, limit := range map[string]time.Duration{"p50": p50Limit, "p95": p95Limit, "p99": p99Limit} {
		if values[name] > limit {
			fail(fmt.Errorf("latency %s = %s exceeds %s", name, values[name], limit))
		}
	}
	fmt.Printf("p50=%s p95=%s p99=%s\n", values["p50"], values["p95"], values["p99"])
}

func percentile(samples []time.Duration, value int) time.Duration {
	if len(samples) == 0 || value < 1 || value > 100 {
		return 0
	}
	index := (len(samples)*value + 99) / 100
	return samples[index-1]
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
