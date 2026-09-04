package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/gongahkia/solomon/internal/updatechannel"
)

func TestManifestInput(t *testing.T) {
	directory := t.TempDir()
	paths := make([]string, 0, 5)
	for _, target := range []struct {
		os, arch, extension string
	}{
		{os: "linux", arch: "amd64", extension: ".tar.gz"},
		{os: "linux", arch: "arm64", extension: ".tar.gz"},
		{os: "darwin", arch: "amd64", extension: ".tar.gz"},
		{os: "darwin", arch: "arm64", extension: ".tar.gz"},
		{os: "windows", arch: "amd64", extension: ".zip"},
	} {
		path := filepath.Join(directory, "solomon_v1.2.3_"+target.os+"_"+target.arch+target.extension)
		if err := os.WriteFile(path, []byte(target.os+target.arch), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path+".sigstore.json", []byte("signature"), 0o600); err != nil {
			t.Fatal(err)
		}
		paths = append(paths, path)
	}
	input, err := manifestInput("stable", "v1.2.3", "0123456789012345678901234567890123456789", paths)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := updatechannel.Generate(input); err != nil {
		t.Fatal(err)
	}
}

func TestManifestInputRejectsMissingSignature(t *testing.T) {
	path := filepath.Join(t.TempDir(), "solomon_v1.2.3_linux_amd64.tar.gz")
	if err := os.WriteFile(path, []byte("artifact"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := manifestInput("stable", "v1.2.3", "0123456789012345678901234567890123456789", []string{path}); err == nil {
		t.Fatal("accepted missing artifact signature")
	}
}
