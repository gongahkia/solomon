package config

import "testing"

func TestDecodeMigrationPreservesLegacyCorrectionPolicy(t *testing.T) {
	cfg, err := decode([]byte(`{"schema_version":1,"mode":"rewrite","auto_apply_safe":true}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.CuratedAutoCorrect || cfg.RiskInterrupt {
		t.Fatalf("unexpected migrated policy: %#v", cfg)
	}
	cfg, err = decode([]byte(`{"schema_version":1,"mode":"interrupt"}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if cfg.CuratedAutoCorrect || !cfg.RiskInterrupt {
		t.Fatalf("unexpected migrated interrupt policy: %#v", cfg)
	}
}
