package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/gongahkia/close-enough/internal/credential"
	"github.com/gongahkia/close-enough/internal/featuregate"
	"github.com/gongahkia/close-enough/internal/securetemp"
)

const CurrentSchemaVersion = 1

type Config struct {
	SchemaVersion       int     `json:"schema_version"`
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
	Home    func() (string, error)
	CWD     func() (string, error)
	Env     func(string) string
	Environ func() []string
}

func Default() Config {
	return Config{SchemaVersion: CurrentSchemaVersion, Mode: "hint", Display: Display{Cause: true, Change: true, Risk: true, Consequence: true}}
}

func (c Config) Features() featuregate.Gates {
	return featuregate.New(c.RegistryEnabled, c.AutoUpdateEnabled)
}

func (c Config) HistoryKeys(store credential.Store) credential.HistoryKeys {
	return credential.NewHistoryKeys(c.LocalHistoryEnabled, store)
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
		if project, ok := projectPath(cwd); ok {
			cfg, err = merge(cfg, project)
			if err != nil {
				return Config{}, err
			}
		}
	}
	values, err := sessionValues(paths)
	if err != nil {
		return Config{}, err
	}
	cfg, err = ApplySessionOverrides(cfg, values)
	if err != nil {
		return Config{}, err
	}
	return cfg, nil
}

var sessionOverrideKeys = map[string]string{
	"CLOSE_ENOUGH_MODE":                  "mode",
	"CLOSE_ENOUGH_AUTO_APPLY_SAFE":       "auto_apply_safe",
	"CLOSE_ENOUGH_LOCAL_HISTORY_ENABLED": "local_history_enabled",
	"CLOSE_ENOUGH_REGISTRY_ENABLED":      "registry_enabled",
	"CLOSE_ENOUGH_AUTO_UPDATE_ENABLED":   "auto_update_enabled",
}

func sessionValues(paths Paths) (map[string]string, error) {
	if paths.Environ == nil {
		values := make(map[string]string, len(sessionOverrideKeys))
		for key := range sessionOverrideKeys {
			values[key] = paths.Env(key)
		}
		return values, nil
	}
	values := map[string]string{}
	for _, entry := range paths.Environ() {
		key, value, ok := strings.Cut(entry, "=")
		if !ok || !strings.HasPrefix(key, "CLOSE_ENOUGH_") {
			continue
		}
		if _, exists := values[key]; exists {
			return nil, fmt.Errorf("duplicate session override %q", key)
		}
		values[key] = value
	}
	return values, nil
}

func ApplySessionOverrides(cfg Config, values map[string]string) (Config, error) {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		value := values[key]
		setting, ok := sessionOverrideKeys[key]
		if !ok {
			return Config{}, fmt.Errorf("unknown session override %q", key)
		}
		if value == "" {
			continue
		}
		if setting != "mode" && value != "true" && value != "false" {
			return Config{}, fmt.Errorf("invalid %s %q: must be true or false", key, value)
		}
		if err := cfg.Set(setting, value); err != nil {
			return Config{}, fmt.Errorf("invalid %s %q: %w", key, value, err)
		}
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
		info, err := os.Stat(candidate)
		if err == nil && info.Mode().IsRegular() && trustedProject(candidate) {
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
	markerInfo, err := os.Lstat(marker)
	if err != nil || !markerInfo.Mode().IsRegular() || !hasSecurePermissions(marker, markerInfo, false) {
		return false
	}
	directory := filepath.Dir(marker)
	directoryInfo, err := os.Lstat(directory)
	if err != nil || !directoryInfo.IsDir() || !hasSecurePermissions(directory, directoryInfo, true) {
		return false
	}
	return ownedByCurrentUser(marker, markerInfo) && ownedByCurrentUser(directory, directoryInfo)
}

func merge(base Config, path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	return decode(data, base)
}

func decode(data []byte, base Config) (Config, error) {
	var envelope struct {
		SchemaVersion *int `json:"schema_version"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	if err := json.Unmarshal(data, &base); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	version := 0
	if envelope.SchemaVersion != nil {
		version = *envelope.SchemaVersion
	}
	migrated, err := migrate(base, version)
	if err != nil {
		return Config{}, err
	}
	base = migrated
	if !validMode(base.Mode) {
		return Config{}, fmt.Errorf("invalid mode %q", base.Mode)
	}
	return base, nil
}

func migrate(cfg Config, version int) (Config, error) {
	if version > CurrentSchemaVersion {
		return Config{}, fmt.Errorf("unsupported configuration schema version %d", version)
	}
	for version < CurrentSchemaVersion {
		switch version {
		case 0:
			cfg.SchemaVersion = 1
			version = 1
		default:
			return Config{}, fmt.Errorf("unsupported configuration schema version %d", version)
		}
	}
	return cfg, nil
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

func Write(path string, cfg Config) (result error) {
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	temporary, err := securetemp.Create(filepath.Dir(path), "."+filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	defer func() {
		result = errors.Join(result, temporary.Cleanup())
	}()
	if _, err := temporary.Write(data); err != nil {
		return err
	}
	return temporary.Commit(path)
}
