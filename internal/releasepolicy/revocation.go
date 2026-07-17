package releasepolicy

import (
	"errors"
	"regexp"
	"strings"
	"time"
)

const RevocationSchemaVersion = 1

var releaseVersion = regexp.MustCompile(`^v[0-9][0-9A-Za-z.+-]*$`)

type Revocation struct {
	SchemaVersion      int    `json:"schema_version"`
	RevokedVersion     string `json:"revoked_version"`
	ReplacementVersion string `json:"replacement_version"`
	Reason             string `json:"reason"`
	RevokedAt          string `json:"revoked_at"`
}

func NewRevocation(revokedVersion, replacementVersion, reason string, at time.Time) (Revocation, error) {
	if !releaseVersion.MatchString(revokedVersion) || !releaseVersion.MatchString(replacementVersion) || revokedVersion == replacementVersion {
		return Revocation{}, errors.New("invalid revoked or replacement release version")
	}
	reason = strings.TrimSpace(reason)
	if reason == "" || len(reason) > 1024 || at.IsZero() {
		return Revocation{}, errors.New("invalid revocation reason or time")
	}
	return Revocation{SchemaVersion: RevocationSchemaVersion, RevokedVersion: revokedVersion, ReplacementVersion: replacementVersion, Reason: reason, RevokedAt: at.UTC().Format(time.RFC3339)}, nil
}
