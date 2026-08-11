package config

import (
	"encoding/json"
	"os"
	"testing"
)

type v1ConfigFixture struct {
	Name  string          `json:"name"`
	Input json.RawMessage `json:"input"`
	Want  struct {
		Mode                     string `json:"mode"`
		CuratedAutoCorrect       bool   `json:"curated_auto_correct"`
		RiskInterrupt            bool   `json:"risk_interrupt"`
		LocalLearningEnabled     bool   `json:"local_learning_enabled"`
		LearningRetentionDays    int    `json:"learning_retention_days"`
		LearnedRuleActionCeiling string `json:"learned_rule_action_ceiling"`
		UndoEnabled              bool   `json:"undo_enabled"`
		UndoTTLSeconds           int    `json:"undo_ttl_seconds"`
	} `json:"want"`
}

func TestDecodeMigrationPreservesLegacyCorrectionPolicy(t *testing.T) {
	cfg, err := decode([]byte(`{"schema_version":1,"mode":"rewrite","auto_apply_safe":true}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.CuratedPacksEnabled || !cfg.CuratedAutoCorrect || cfg.RiskInterrupt || !cfg.UndoEnabled || cfg.UndoTTLSeconds != defaultUndoTTLSeconds {
		t.Fatalf("unexpected migrated policy: %#v", cfg)
	}
	cfg, err = decode([]byte(`{"schema_version":1,"mode":"interrupt"}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.CuratedPacksEnabled || cfg.CuratedAutoCorrect || !cfg.RiskInterrupt || !cfg.UndoEnabled || cfg.UndoTTLSeconds != defaultUndoTTLSeconds {
		t.Fatalf("unexpected migrated interrupt policy: %#v", cfg)
	}
}

func TestDecodeV2PreservesUndoSettingsFromBase(t *testing.T) {
	base := Default()
	base.UndoEnabled, base.UndoTTLSeconds = false, 45
	cfg, err := decode([]byte(`{"schema_version":2,"mode":"hint"}`), base)
	if err != nil || cfg.SchemaVersion != CurrentSchemaVersion || cfg.UndoEnabled || cfg.UndoTTLSeconds != 45 {
		t.Fatalf("migrated v2 config = %#v, %v", cfg, err)
	}
}

func TestV1ConfigurationFixtureCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/v1_configurations.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []v1ConfigFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("v1 configuration corpus is empty")
	}
	for _, fixture := range fixtures {
		t.Run(fixture.Name, func(t *testing.T) {
			if fixture.Name == "" || len(fixture.Input) == 0 {
				t.Fatalf("invalid v1 configuration fixture: %#v", fixture)
			}
			cfg, err := decode(fixture.Input, Default())
			if err != nil {
				t.Fatal(err)
			}
			if cfg.SchemaVersion != CurrentSchemaVersion || cfg.Mode != fixture.Want.Mode || cfg.CuratedAutoCorrect != fixture.Want.CuratedAutoCorrect || cfg.RiskInterrupt != fixture.Want.RiskInterrupt || cfg.LocalLearningEnabled != fixture.Want.LocalLearningEnabled || cfg.LearningRetentionDays != fixture.Want.LearningRetentionDays || cfg.LearnedRuleActionCeiling != fixture.Want.LearnedRuleActionCeiling || cfg.UndoEnabled != fixture.Want.UndoEnabled || cfg.UndoTTLSeconds != fixture.Want.UndoTTLSeconds {
				t.Fatalf("decoded v1 config = %#v, want %#v", cfg, fixture.Want)
			}
		})
	}
}
