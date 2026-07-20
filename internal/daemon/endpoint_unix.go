//go:build !windows

package daemon

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
)

func LocalEndpoint(runtimeDirectory string) (Endpoint, error) {
	if err := PrepareDirectory(runtimeDirectory); err != nil {
		return Endpoint{}, err
	}
	path := filepath.Join(runtimeDirectory, "daemon.sock")
	if len(path) < 100 {
		return Endpoint{Network: "unix", Address: path}, nil
	}
	sum := sha256.Sum256([]byte(runtimeDirectory))
	directory := filepath.Join(os.TempDir(), "close-enough-"+hex.EncodeToString(sum[:8]))
	if err := PrepareDirectory(directory); err != nil {
		return Endpoint{}, err
	}
	path = filepath.Join(directory, "daemon.sock")
	if len(path) >= 100 {
		return Endpoint{}, errors.New("daemon socket fallback path is too long")
	}
	return Endpoint{Network: "unix", Address: path}, nil
}
