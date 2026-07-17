package packs

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
)

const EngineVersion = "1.0.0"

var supportedCapabilities = map[string]struct{}{
	"matcher-v1": {}, "transformation-v1": {}, "explanation-v1": {}, "risk-v1": {},
}

func validateCompatibilityMetadata(pack Pack) error {
	if pack.MinEngineVersion != "" && !semanticVersion(pack.MinEngineVersion) {
		return errors.New("minimum engine version must be semantic")
	}
	seen := map[string]struct{}{}
	for _, capability := range pack.Capabilities {
		if !identifier(capability) {
			return fmt.Errorf("invalid capability %q", capability)
		}
		if _, exists := seen[capability]; exists {
			return fmt.Errorf("duplicate capability %q", capability)
		}
		seen[capability] = struct{}{}
	}
	return nil
}

func (p Pack) CheckCompatibility(engineVersion string) error {
	if err := p.Validate(); err != nil {
		return err
	}
	if !semanticVersion(engineVersion) {
		return fmt.Errorf("invalid engine version %q", engineVersion)
	}
	if p.MinEngineVersion != "" && compareVersion(engineVersion, p.MinEngineVersion) < 0 {
		return fmt.Errorf("pack requires engine version %s", p.MinEngineVersion)
	}
	for _, capability := range p.Capabilities {
		if _, supported := supportedCapabilities[capability]; !supported {
			return fmt.Errorf("unsupported pack capability %q", capability)
		}
	}
	return nil
}

func compareVersion(left, right string) int {
	leftCore, leftPre := splitVersion(left)
	rightCore, rightPre := splitVersion(right)
	leftParts, rightParts := strings.Split(leftCore, "."), strings.Split(rightCore, ".")
	for index := range leftParts {
		l, _ := strconv.Atoi(leftParts[index])
		r, _ := strconv.Atoi(rightParts[index])
		if l < r {
			return -1
		}
		if l > r {
			return 1
		}
	}
	return comparePrerelease(leftPre, rightPre)
}

func splitVersion(value string) (string, string) {
	value, _, _ = strings.Cut(value, "+")
	core, prerelease, _ := strings.Cut(value, "-")
	return core, prerelease
}

func comparePrerelease(left, right string) int {
	if left == "" && right != "" {
		return 1
	}
	if left != "" && right == "" {
		return -1
	}
	leftParts, rightParts := strings.Split(left, "."), strings.Split(right, ".")
	for index := 0; index < len(leftParts) && index < len(rightParts); index++ {
		l, lNumber := strconv.Atoi(leftParts[index])
		r, rNumber := strconv.Atoi(rightParts[index])
		if lNumber == nil && rNumber == nil {
			if l < r {
				return -1
			}
			if l > r {
				return 1
			}
			continue
		}
		if lNumber == nil {
			return -1
		}
		if rNumber == nil {
			return 1
		}
		if l < r {
			return -1
		}
		if l > r {
			return 1
		}
	}
	if len(leftParts) < len(rightParts) {
		return -1
	}
	if len(leftParts) > len(rightParts) {
		return 1
	}
	return 0
}
