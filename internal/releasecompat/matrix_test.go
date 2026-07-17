package releasecompat

import (
	"strings"
	"testing"
)

func TestValidate(t *testing.T) {
	platforms := []string{"linux/amd64", "linux/arm64", "darwin/amd64", "darwin/arm64", "windows/amd64"}
	if err := Validate(platforms); err != nil {
		t.Fatal(err)
	}
	data, err := JSON()
	if err != nil || !strings.Contains(string(data), `"runner":"windows-latest"`) {
		t.Fatalf("matrix JSON = %q, %v", data, err)
	}
}

func TestValidateRejectsUnsupportedTarget(t *testing.T) {
	platforms := []string{"linux/amd64", "linux/arm64", "darwin/amd64", "darwin/arm64"}
	if err := Validate(platforms); err == nil {
		t.Fatal("accepted missing Windows target")
	}
}

func TestParsePlatforms(t *testing.T) {
	platforms := ParsePlatforms("windows/amd64\nlinux/arm64\nlinux/amd64\n")
	if strings.Join(platforms, ",") != "linux/amd64,linux/arm64,windows/amd64" {
		t.Fatalf("platforms = %q", platforms)
	}
}
