package daemon

import (
	"errors"
	"fmt"
	"path/filepath"
)

func RuntimeDirectory(home func() (string, error), environment func(string) string) (string, error) {
	if environment == nil {
		return "", errors.New("runtime environment lookup is required")
	}
	if value := environment("XDG_RUNTIME_DIR"); filepath.IsAbs(value) {
		return filepath.Join(value, "close-enough"), nil
	}
	if home == nil {
		return "", errors.New("home directory lookup is required")
	}
	value, err := home()
	if err != nil {
		return "", err
	}
	if value == "" || !filepath.IsAbs(value) {
		return "", fmt.Errorf("home directory must be absolute")
	}
	return filepath.Join(value, ".cache", "close-enough", "runtime"), nil
}
