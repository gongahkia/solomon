package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReproducibleLocalBuild(t *testing.T) {
	first := filepath.Join(t.TempDir(), "close-enough")
	second := filepath.Join(t.TempDir(), "close-enough")
	for _, output := range []string{first, second} {
		command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", output, ".")
		if data, err := command.CombinedOutput(); err != nil {
			t.Fatalf("build %q: %v\n%s", output, err, data)
		}
	}
	firstBinary, err := os.ReadFile(first)
	if err != nil {
		t.Fatal(err)
	}
	secondBinary, err := os.ReadFile(second)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstBinary, secondBinary) {
		t.Fatal("build outputs differ")
	}
	firstData, err := exec.Command(first, "version").Output()
	if err != nil {
		t.Fatal(err)
	}
	secondData, err := exec.Command(second, "version").Output()
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstData, secondData) || string(firstData) != "close-enough dev\n" {
		t.Fatalf("unexpected version output: %q, %q", firstData, secondData)
	}
}

func TestLocalBuildRejectsMissingPackage(t *testing.T) {
	command := exec.Command("go", "build", "-mod=readonly", "./missing-package")
	if data, err := command.CombinedOutput(); err == nil {
		t.Fatalf("missing package built successfully: %s", data)
	}
}
