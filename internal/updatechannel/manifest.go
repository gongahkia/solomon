package updatechannel

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

const SchemaVersion = 1

var versionPattern = regexp.MustCompile(`^v[0-9][0-9A-Za-z.+-]*$`)
var commitPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

type ArtifactInput struct {
	Name          string
	Data          []byte
	SignatureName string
	Signature     []byte
}

type Input struct {
	Channel   string
	Version   string
	Commit    string
	Artifacts []ArtifactInput
}

type Manifest struct {
	SchemaVersion int        `json:"schema_version"`
	Channel       string     `json:"channel"`
	Version       string     `json:"version"`
	Commit        string     `json:"commit"`
	Artifacts     []Artifact `json:"artifacts"`
}

type Artifact struct {
	OS        string `json:"os"`
	Arch      string `json:"arch"`
	Filename  string `json:"filename"`
	SHA256    string `json:"sha256"`
	Signature string `json:"signature"`
}

func Generate(input Input) (Manifest, error) {
	if input.Channel != "stable" || !versionPattern.MatchString(input.Version) || !commitPattern.MatchString(input.Commit) || len(input.Artifacts) != 5 {
		return Manifest{}, errors.New("invalid update manifest input")
	}
	artifacts := make([]Artifact, 0, len(input.Artifacts))
	seen := map[string]struct{}{}
	for _, source := range input.Artifacts {
		artifact, err := parseArtifact(source, input.Version)
		if err != nil {
			return Manifest{}, err
		}
		key := artifact.OS + "/" + artifact.Arch
		if _, duplicate := seen[key]; duplicate {
			return Manifest{}, fmt.Errorf("duplicate update target %s", key)
		}
		seen[key] = struct{}{}
		artifacts = append(artifacts, artifact)
	}
	if !completeTargets(seen) {
		return Manifest{}, errors.New("incomplete update target set")
	}
	sort.Slice(artifacts, func(left, right int) bool {
		if artifacts[left].OS == artifacts[right].OS {
			return artifacts[left].Arch < artifacts[right].Arch
		}
		return artifacts[left].OS < artifacts[right].OS
	})
	return Manifest{SchemaVersion: SchemaVersion, Channel: input.Channel, Version: input.Version, Commit: input.Commit, Artifacts: artifacts}, nil
}

func parseArtifact(source ArtifactInput, version string) (Artifact, error) {
	if len(source.Data) == 0 || len(source.Signature) == 0 || source.SignatureName != source.Name+".sigstore.json" {
		return Artifact{}, errors.New("invalid update artifact signature")
	}
	name := source.Name
	extension := ""
	switch {
	case strings.HasSuffix(name, ".tar.gz"):
		extension = ".tar.gz"
	case strings.HasSuffix(name, ".zip"):
		extension = ".zip"
	default:
		return Artifact{}, errors.New("invalid update artifact extension")
	}
	parts := strings.Split(strings.TrimSuffix(name, extension), "_")
	if len(parts) != 4 || parts[0] != "close-enough" || parts[1] != version {
		return Artifact{}, errors.New("invalid update artifact name")
	}
	osName, arch := parts[2], parts[3]
	if !validTarget(osName, arch, extension) {
		return Artifact{}, errors.New("unsupported update target")
	}
	sum := sha256.Sum256(source.Data)
	return Artifact{OS: osName, Arch: arch, Filename: name, SHA256: hex.EncodeToString(sum[:]), Signature: source.SignatureName}, nil
}

func completeTargets(targets map[string]struct{}) bool {
	if len(targets) != 5 {
		return false
	}
	for _, target := range []string{"linux/amd64", "linux/arm64", "darwin/amd64", "darwin/arm64", "windows/amd64"} {
		if _, ok := targets[target]; !ok {
			return false
		}
	}
	return true
}

func validTarget(osName, arch, extension string) bool {
	switch osName + "/" + arch + "/" + extension {
	case "linux/amd64/.tar.gz", "linux/arm64/.tar.gz", "darwin/amd64/.tar.gz", "darwin/arm64/.tar.gz", "windows/amd64/.zip":
		return true
	default:
		return false
	}
}
