package main

import (
	"archive/tar"
	"compress/gzip"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestReleasePackNameScript(t *testing.T) {
	command := exec.Command("sh", "../../scripts/release-pack-name.sh", "v1.2.3-rc.1+build.7")
	if data, err := command.Output(); err != nil || string(data) != "close-enough-packs_v1.2.3-rc.1+build.7.tar.gz\n" {
		t.Fatalf("pack release name = %q, %v", data, err)
	}
}

func TestReleasePackBundleScript(t *testing.T) {
	directory := t.TempDir()
	source := filepath.Join(directory, "packs")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "alpha.json"), []byte("{\"id\":\"alpha\"}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "beta.json"), []byte("{\"id\":\"beta\"}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	validator := writePackValidator(t, directory, "exit 0")
	archive := filepath.Join(directory, "close-enough-packs_v1.2.3.tar.gz")
	if data, err := exec.Command("sh", "../../scripts/release-pack-bundle.sh", validator, source, archive, "close-enough-packs_v1.2.3").CombinedOutput(); err != nil {
		t.Fatalf("bundle release packs: %v\n%s", err, data)
	}
	file, err := os.Open(archive)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	compressed, err := gzip.NewReader(file)
	if err != nil {
		t.Fatal(err)
	}
	defer compressed.Close()
	reader := tar.NewReader(compressed)
	contents := map[string]string{}
	for {
		header, err := reader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if header.Typeflag != tar.TypeReg {
			continue
		}
		data, err := io.ReadAll(reader)
		if err != nil {
			t.Fatal(err)
		}
		contents[header.Name] = string(data)
	}
	if contents["close-enough-packs_v1.2.3/alpha.json"] != "{\"id\":\"alpha\"}\n" || contents["close-enough-packs_v1.2.3/beta.json"] != "{\"id\":\"beta\"}\n" {
		t.Fatalf("pack bundle contents = %#v", contents)
	}
}

func TestReleasePackBundleScriptRejectsFailedValidation(t *testing.T) {
	directory := t.TempDir()
	source := filepath.Join(directory, "packs")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "alpha.json"), []byte("{}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	validator := writePackValidator(t, directory, "exit 9")
	archive := filepath.Join(directory, "close-enough-packs_v1.2.3.tar.gz")
	if data, err := exec.Command("sh", "../../scripts/release-pack-bundle.sh", validator, source, archive, "close-enough-packs_v1.2.3").CombinedOutput(); err == nil {
		t.Fatalf("invalid pack bundle succeeded: %s", data)
	}
	if _, err := os.Stat(archive); !os.IsNotExist(err) {
		t.Fatalf("failed pack bundle archive = %v", err)
	}
}

func writePackValidator(t *testing.T, directory, body string) string {
	t.Helper()
	validator := filepath.Join(directory, "close-enough")
	if err := os.WriteFile(validator, []byte("#!/bin/sh\nset -eu\n[ \"$1\" = pack ]\n[ \"$2\" = validate ]\n"+body+"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	return validator
}
