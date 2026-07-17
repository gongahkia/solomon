package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
)

type Config struct {
	Mode                string  `json:"mode"`
	Display             Display `json:"display"`
	AutoApplySafe       bool    `json:"auto_apply_safe"`
	LocalHistoryEnabled bool    `json:"local_history_enabled"`
	RegistryEnabled     bool    `json:"registry_enabled"`
	AutoUpdateEnabled   bool    `json:"auto_update_enabled"`
}

type Display struct {
	Cause       bool `json:"cause"`
	Change      bool `json:"change"`
	Risk        bool `json:"risk"`
	Consequence bool `json:"consequence"`
	Trace       bool `json:"trace"`
}

type Paths struct {
	Home func() (string, error)
	CWD  func() (string, error)
	Env  func(string) string
}

func Default() Config {
	return Config{Mode: "hint", Display: Display{Cause: true, Change: true, Risk: true, Consequence: true}}
}

func GlobalPath(home func() (string, error)) (string, error) {
	return globalPath(home, os.Getenv)
}

func globalPath(home func() (string, error), env func(string) string) (string, error) {
	base := env("XDG_CONFIG_HOME")
	if base == "" || !filepath.IsAbs(base) {
		value, err := home()
		if err != nil {
			return "", err
		}
		base = filepath.Join(value, ".config")
	}
	return filepath.Join(base, "close-enough", "config.json"), nil
}

func Load(paths Paths) (Config, error) {
	global, err := globalPath(paths.Home, paths.Env)
	if err != nil {
		return Config{}, err
	}
	cfg, err := LoadGlobal(global)
	if err != nil {
		return Config{}, err
	}
	cwd, err := paths.CWD()
	if err == nil {
		if project, ok := projectPath(cwd); ok && trustedProject(project) {
			cfg, err = merge(cfg, project)
			if err != nil {
				return Config{}, err
			}
		}
	}
	if mode := paths.Env("CLOSE_ENOUGH_MODE"); mode != "" {
		if !validMode(mode) {
			return Config{}, fmt.Errorf("invalid CLOSE_ENOUGH_MODE %q", mode)
		}
		cfg.Mode = mode
	}
	return cfg, nil
}

func LoadGlobal(path string) (Config, error) {
	cfg := Default()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return Config{}, err
	}
	return decode(data, cfg)
}

func projectPath(cwd string) (string, bool) {
	for dir := cwd; ; dir = filepath.Dir(dir) {
		candidate := filepath.Join(dir, ".close-enough", "config.json")
		if _, err := os.Stat(candidate); err == nil {
			return candidate, true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", false
		}
	}
}

func trustedProject(path string) bool {
	marker := filepath.Join(filepath.Dir(path), "trusted")
	info, err := os.Stat(marker)
	if err != nil || info.Mode().Perm()&0o022 != 0 {
		return false
	}
	return info.Mode().Perm()&0o077 == 0
}

func merge(base Config, path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	return decode(data, base)
}

func decode(data []byte, base Config) (Config, error) {
	if err := json.Unmarshal(data, &base); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	if !validMode(base.Mode) {
		return Config{}, fmt.Errorf("invalid mode %q", base.Mode)
	}
	return base, nil
}

func validMode(value string) bool {
	return value == "hint" || value == "interrupt" || value == "off" || value == "rewrite"
}

func (c *Config) Set(key, value string) error {
	switch key {
	case "mode":
		if !validMode(value) {
			return errors.New("mode must be hint, interrupt, off, or rewrite")
		}
		c.Mode = value
	case "auto_apply_safe", "local_history_enabled", "registry_enabled", "auto_update_enabled":
		parsed, err := strconv.ParseBool(value)
		if err != nil {
			return err
		}
		switch key {
		case "auto_apply_safe":
			c.AutoApplySafe = parsed
		case "local_history_enabled":
			c.LocalHistoryEnabled = parsed
		case "registry_enabled":
			c.RegistryEnabled = parsed
		case "auto_update_enabled":
			c.AutoUpdateEnabled = parsed
		}
	default:
		return fmt.Errorf("unknown configuration key %q", key)
	}
	return nil
}

func Write(path string, cfg Config) error {
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0o600)
}
