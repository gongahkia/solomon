//go:build windows

package daemon

import (
	"crypto/sha256"
	"encoding/hex"
)

func LocalEndpoint(runtimeDirectory string) (Endpoint, error) {
	if err := PrepareDirectory(runtimeDirectory); err != nil {
		return Endpoint{}, err
	}
	sum := sha256.Sum256([]byte(runtimeDirectory))
	return Endpoint{Network: "npipe", Address: `\\.\pipe\close-enough-` + hex.EncodeToString(sum[:16])}, nil
}
