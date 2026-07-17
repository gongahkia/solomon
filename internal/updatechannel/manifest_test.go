package updatechannel

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func TestGenerate(t *testing.T) {
	input := Input{Channel: "stable", Version: "v1.2.3", Commit: "0123456789012345678901234567890123456789"}
	for _, target := range []struct {
		os, arch, extension string
	}{
		{os: "linux", arch: "amd64", extension: ".tar.gz"},
		{os: "linux", arch: "arm64", extension: ".tar.gz"},
		{os: "darwin", arch: "amd64", extension: ".tar.gz"},
		{os: "darwin", arch: "arm64", extension: ".tar.gz"},
		{os: "windows", arch: "amd64", extension: ".zip"},
	} {
		name := "close-enough_v1.2.3_" + target.os + "_" + target.arch + target.extension
		input.Artifacts = append(input.Artifacts, ArtifactInput{Name: name, Data: []byte(target.os + target.arch), SignatureName: name + ".sigstore.json", Signature: []byte("signature")})
	}
	manifest, err := Generate(input)
	if err != nil {
		t.Fatal(err)
	}
	if len(manifest.Artifacts) != 5 || manifest.Artifacts[0].OS != "darwin" || manifest.Artifacts[4].OS != "windows" {
		t.Fatalf("manifest artifacts = %#v", manifest.Artifacts)
	}
	sum := sha256.Sum256([]byte("linuxamd64"))
	if manifest.Artifacts[2].SHA256 != hex.EncodeToString(sum[:]) {
		t.Fatalf("linux checksum = %q", manifest.Artifacts[2].SHA256)
	}
}

func TestGenerateRejectsInvalidInput(t *testing.T) {
	input := Input{Channel: "stable", Version: "v1.2.3", Commit: "0123456789012345678901234567890123456789"}
	if _, err := Generate(input); err == nil {
		t.Fatal("accepted incomplete targets")
	}
	input.Artifacts = make([]ArtifactInput, 5)
	for index := range input.Artifacts {
		input.Artifacts[index] = ArtifactInput{Name: "close-enough_v1.2.3_linux_amd64.tar.gz", Data: []byte("artifact"), SignatureName: "wrong", Signature: []byte("signature")}
	}
	if _, err := Generate(input); err == nil {
		t.Fatal("accepted invalid signature association")
	}
}
