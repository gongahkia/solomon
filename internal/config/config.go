package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/gongahkia/close-enough/internal/filesystem"
	"github.com/gongahkia/close-enough/internal/securetemp"
)

const (
	CurrentSchemaVersion         = 7
	maxRuleExceptionCommandBytes = 8 << 10
	defaultLearningRetentionDays = 30
	maxLearningRetentionDays     = 90
	defaultUndoTTLSeconds        = 30
	maxUndoTTLSeconds            = 300
)

type RuleException struct {
	ID      string `json:"id"`
	Command string `json:"command"`
}

type Config struct {
	SchemaVersion int     `json:"schema_version"`
	Mode          string  `json:"mode"`
	Display       Display `json:"display"`
	AutoApplySafe bool    `json:"auto_apply_safe"`
	// LocalHistoryEnabled is retained only to migrate pre-v6 configuration.
	// The product has no history persistence or ranking backend.
	LocalHistoryEnabled      bool            `json:"local_history_enabled,omitempty"`
	CuratedPacksEnabled      bool            `json:"curated_packs_enabled"`
	RiskInterrupt            bool            `json:"risk_interrupt"`
	LocalLearningEnabled     bool            `json:"local_learning_enabled"`
	LearningRetentionDays    int             `json:"learning_retention_days"`
	LearnedRuleActionCeiling string          `json:"learned_rule_action_ceiling"`
	UndoEnabled              bool            `json:"undo_enabled"`
	UndoTTLSeconds           int             `json:"undo_ttl_seconds"`
	RuleExceptions           []RuleException `json:"rule_exceptions,omitempty"`
}

type Display struct {
	Cause       bool `json:"cause"`
	Change      bool `json:"change"`
	Confidence  bool `json:"confidence"`
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
	return Config{SchemaVersion: CurrentSchemaVersion, Mode: "hint", CuratedPacksEnabled: true, LearningRetentionDays: defaultLearningRetentionDays, LearnedRuleActionCeiling: "hint", UndoEnabled: true, UndoTTLSeconds: defaultUndoTTLSeconds, Display: Display{Cause: true, Change: true, Confidence: true, Risk: true, Consequence: true}}
}

func (c Config) HasRuleException(command string) bool {
	for _, exception := range c.RuleExceptions {
		if exception.Command == command {
			return true
		}
	}
	return false
}

func (c *Config) AddRuleException(exception RuleException) error {
	if err := validateRuleException(exception); err != nil {
		return err
	}
	for _, existing := range c.RuleExceptions {
		if existing.ID == exception.ID {
			return fmt.Errorf("rule exception %q already exists", exception.ID)
		}
		if existing.Command == exception.Command {
			return errors.New("rule exception command already exists")
		}
	}
	c.RuleExceptions = append(c.RuleExceptions, exception)
	return nil
}

func (c *Config) UpdateRuleException(id, command string) error {
	if !validRuleExceptionID(id) {
		return fmt.Errorf("invalid rule exception id %q", id)
	}
	if err := validateRuleException(RuleException{ID: id, Command: command}); err != nil {
		return err
	}
	for index, existing := range c.RuleExceptions {
		if existing.ID != id && existing.Command == command {
			return errors.New("rule exception command already exists")
		}
		if existing.ID == id {
			c.RuleExceptions[index].Command = command
			return nil
		}
	}
	return fmt.Errorf("rule exception %q does not exist", id)
}

func (c *Config) RemoveRuleException(id string) error {
	if !validRuleExceptionID(id) {
		return fmt.Errorf("invalid rule exception id %q", id)
	}
	for index, exception := range c.RuleExceptions {
		if exception.ID == id {
			c.RuleExceptions = append(c.RuleExceptions[:index], c.RuleExceptions[index+1:]...)
			return nil
		}
	}
	return fmt.Errorf("rule exception %q does not exist", id)
}

func validateRuleExceptions(exceptions []RuleException) error {
	seenIDs := map[string]struct{}{}
	seenCommands := map[string]struct{}{}
	for _, exception := range exceptions {
		if err := validateRuleException(exception); err != nil {
			return err
		}
		if _, exists := seenIDs[exception.ID]; exists {
			return fmt.Errorf("duplicate rule exception id %q", exception.ID)
		}
		if _, exists := seenCommands[exception.Command]; exists {
			return errors.New("duplicate rule exception command")
		}
		seenIDs[exception.ID] = struct{}{}
		seenCommands[exception.Command] = struct{}{}
	}
	return nil
}

func validateRuleException(exception RuleException) error {
	if !validRuleExceptionID(exception.ID) {
		return fmt.Errorf("invalid rule exception id %q", exception.ID)
	}
	if strings.TrimSpace(exception.Command) == "" || len(exception.Command) > maxRuleExceptionCommandBytes {
		return errors.New("rule exception command must be non-empty and within the input limit")
	}
	return nil
}

func validRuleExceptionID(value string) bool {
	if len(value) == 0 || len(value) > 64 || value[0] < 'a' || value[0] > 'z' {
		return false
	}
	for _, character := range value[1:] {
		if character >= 'a' && character <= 'z' || character >= '0' && character <= '9' || character == '-' || character == '_' {
			continue
		}
		return false
	}
	return true
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
			cfg, err = mergeApprovedProject(cfg, project)
			if err != nil {
				return Config{}, err
			}
		}
	}
	cfg, err = applySessionPrecedence(cfg, paths)
	if err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func applySessionPrecedence(base Config, paths Paths) (Config, error) {
	values, err := sessionValues(paths)
	if err != nil {
		return Config{}, err
	}
	return ApplySessionOverrides(base, values)
}

var sessionOverrideKeys = map[string]string{
	"CLOSE_ENOUGH_MODE":                   "mode",
	"CLOSE_ENOUGH_AUTO_APPLY_SAFE":        "auto_apply_safe",
	"CLOSE_ENOUGH_CURATED_PACKS_ENABLED":  "curated_packs_enabled",
	"CLOSE_ENOUGH_RISK_INTERRUPT":         "risk_interrupt",
	"CLOSE_ENOUGH_LOCAL_LEARNING_ENABLED": "local_learning_enabled",
	"CLOSE_ENOUGH_UNDO_ENABLED":           "undo_enabled",
	"CLOSE_ENOUGH_UNDO_TTL_SECONDS":       "undo_ttl_seconds",
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
		if key == "CLOSE_ENOUGH_REGISTRY_ENABLED" || key == "CLOSE_ENOUGH_AUTO_UPDATE_ENABLED" {
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
		if setting != "mode" && setting != "undo_ttl_seconds" && value != "true" && value != "false" {
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
	data, err := readConfigFile(path)
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
	capabilities := filesystem.Current()
	if !capabilities.Supports(filesystem.RestrictivePermissions) || !capabilities.Supports(filesystem.OwnerVerification) {
		return false
	}
	configInfo, err := os.Lstat(path)
	if err != nil || !configInfo.Mode().IsRegular() || !hasSecurePermissions(path, configInfo, false) {
		return false
	}
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
	return ownedByCurrentUser(path, configInfo) && ownedByCurrentUser(marker, markerInfo) && ownedByCurrentUser(directory, directoryInfo)
}

func mergeApprovedProject(base Config, path string) (Config, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return base, nil
	}
	if err != nil {
		return Config{}, err
	}
	if !info.Mode().IsRegular() || !trustedProject(path) {
		return base, nil
	}
	data, err := readConfigFile(path)
	if err != nil {
		return Config{}, err
	}
	return decode(data, base)
}

func decode(data []byte, base Config) (Config, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	if fields == nil {
		return Config{}, errors.New("parse config: configuration must be a JSON object")
	}
	delete(fields, "registry_enabled")
	delete(fields, "auto_update_enabled")
	version := 0
	if value, ok := fields["schema_version"]; ok {
		if bytes.Equal(value, []byte("null")) {
			return Config{}, errors.New("parse config: schema_version must be an integer")
		}
		if err := json.Unmarshal(value, &version); err != nil {
			return Config{}, fmt.Errorf("parse config: schema_version must be an integer: %w", err)
		}
	}
	// curated_auto_correct was exposed but never controlled runtime behavior.
	// Accept it only in legacy configurations so v7 retains strict unknown-field
	// validation while older files can migrate cleanly.
	if version <= 6 {
		delete(fields, "curated_auto_correct")
	}
	filtered, err := json.Marshal(fields)
	if err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	data = filtered
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&base); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	migrated, err := migrate(base, version)
	if err != nil {
		return Config{}, err
	}
	base = migrated
	if !validMode(base.Mode) {
		return Config{}, fmt.Errorf("invalid mode %q", base.Mode)
	}
	if !validLearnedRuleAction(base.LearnedRuleActionCeiling) {
		return Config{}, fmt.Errorf("invalid learned rule action ceiling %q", base.LearnedRuleActionCeiling)
	}
	if base.LearningRetentionDays < 1 || base.LearningRetentionDays > maxLearningRetentionDays {
		return Config{}, fmt.Errorf("learning retention days must be between 1 and %d", maxLearningRetentionDays)
	}
	if base.UndoTTLSeconds < 1 || base.UndoTTLSeconds > maxUndoTTLSeconds {
		return Config{}, fmt.Errorf("undo ttl seconds must be between 1 and %d", maxUndoTTLSeconds)
	}
	if base.LocalHistoryEnabled {
		return Config{}, errors.New("local history is not supported")
	}
	if err := validateRuleExceptions(base.RuleExceptions); err != nil {
		return Config{}, err
	}
	return base, nil
}

func readConfigFile(path string) ([]byte, error) {
	// #nosec G304 -- These are the configured global or ownership-checked project configuration paths.
	return os.ReadFile(path)
}

func migrate(cfg Config, version int) (Config, error) {
	if version > CurrentSchemaVersion {
		return Config{}, fmt.Errorf("unsupported configuration schema version %d", version)
	}
	for version < CurrentSchemaVersion {
		switch version {
		case 0:
			cfg.RiskInterrupt = cfg.Mode == "interrupt"
			cfg.SchemaVersion = 1
			version = 1
		case 1:
			cfg.RiskInterrupt = cfg.Mode == "interrupt"
			cfg.SchemaVersion = 2
			version = 2
		case 2:
			cfg.SchemaVersion = 3
			version = 3
		case 3:
			cfg.CuratedPacksEnabled = true
			cfg.SchemaVersion = 4
			version = 4
		case 4:
			// A schema migration must not retain authority to edit or block a
			// command. Users can opt in again after reviewing the new policy.
			if cfg.Mode == "rewrite" || cfg.Mode == "interrupt" {
				cfg.Mode = "hint"
				cfg.AutoApplySafe = false
				cfg.RiskInterrupt = false
			}
			cfg.SchemaVersion = 5
			version = 5
		case 5:
			// History was never wired to a production backend. Remove the
			// old opt-in instead of retaining a configuration claim that the
			// runtime cannot honor.
			cfg.LocalHistoryEnabled = false
			cfg.SchemaVersion = 6
			version = 6
		case 6:
			// curated_auto_correct never influenced decisions. Drop it instead of
			// preserving a configuration claim the runtime cannot honor.
			cfg.SchemaVersion = 7
			version = 7
		default:
			return Config{}, fmt.Errorf("unsupported configuration schema version %d", version)
		}
	}
	return cfg, nil
}

func validMode(value string) bool {
	return value == "hint" || value == "interrupt" || value == "off" || value == "rewrite"
}

func validLearnedRuleAction(value string) bool {
	return value == "off" || value == "hint" || value == "rewrite"
}

func (c *Config) Set(key, value string) error {
	switch key {
	case "mode":
		if !validMode(value) {
			return errors.New("mode must be hint, interrupt, off, or rewrite")
		}
		c.Mode = value
	case "auto_apply_safe", "curated_packs_enabled", "risk_interrupt", "local_learning_enabled", "undo_enabled", "display.cause", "display.change", "display.confidence", "display.risk", "display.consequence", "display.trace":
		parsed, err := strconv.ParseBool(value)
		if err != nil {
			return err
		}
		switch key {
		case "auto_apply_safe":
			c.AutoApplySafe = parsed
		case "curated_packs_enabled":
			c.CuratedPacksEnabled = parsed
		case "risk_interrupt":
			c.RiskInterrupt = parsed
		case "local_learning_enabled":
			c.LocalLearningEnabled = parsed
		case "undo_enabled":
			c.UndoEnabled = parsed
		case "display.cause":
			c.Display.Cause = parsed
		case "display.change":
			c.Display.Change = parsed
		case "display.confidence":
			c.Display.Confidence = parsed
		case "display.risk":
			c.Display.Risk = parsed
		case "display.consequence":
			c.Display.Consequence = parsed
		case "display.trace":
			c.Display.Trace = parsed
		}
	case "learning_retention_days":
		parsed, err := strconv.Atoi(value)
		if err != nil || parsed < 1 || parsed > maxLearningRetentionDays {
			return fmt.Errorf("learning_retention_days must be between 1 and %d", maxLearningRetentionDays)
		}
		c.LearningRetentionDays = parsed
	case "undo_ttl_seconds":
		parsed, err := strconv.Atoi(value)
		if err != nil || parsed < 1 || parsed > maxUndoTTLSeconds {
			return fmt.Errorf("undo_ttl_seconds must be between 1 and %d", maxUndoTTLSeconds)
		}
		c.UndoTTLSeconds = parsed
	case "learned_rule_action_ceiling":
		if !validLearnedRuleAction(value) {
			return errors.New("learned_rule_action_ceiling must be off, hint, or rewrite")
		}
		c.LearnedRuleActionCeiling = value
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
