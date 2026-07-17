package releasecompat

import (
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
)

type Target struct {
	GOOS   string `json:"goos"`
	GOARCH string `json:"goarch"`
	Runner string `json:"runner"`
}

type Matrix struct {
	Include []Target `json:"include"`
}

func Targets() []Target {
	return []Target{
		{GOOS: "linux", GOARCH: "amd64", Runner: "ubuntu-latest"},
		{GOOS: "linux", GOARCH: "arm64", Runner: "ubuntu-24.04-arm"},
		{GOOS: "darwin", GOARCH: "amd64", Runner: "macos-15-intel"},
		{GOOS: "darwin", GOARCH: "arm64", Runner: "macos-latest"},
		{GOOS: "windows", GOARCH: "amd64", Runner: "windows-latest"},
	}
}

func Validate(supported []string) error {
	available := map[string]struct{}{}
	for _, platform := range supported {
		available[platform] = struct{}{}
	}
	seen := map[string]struct{}{}
	for _, target := range Targets() {
		key := target.GOOS + "/" + target.GOARCH
		if _, duplicate := seen[key]; duplicate {
			return fmt.Errorf("duplicate release target %s", key)
		}
		if _, exists := available[key]; !exists {
			return fmt.Errorf("unsupported Go release target %s", key)
		}
		seen[key] = struct{}{}
	}
	if len(seen) != 5 {
		return errors.New("incomplete release target matrix")
	}
	return nil
}

func ParsePlatforms(data string) []string {
	platforms := strings.Fields(data)
	sort.Strings(platforms)
	return platforms
}

func JSON() ([]byte, error) { return json.Marshal(Matrix{Include: Targets()}) }
