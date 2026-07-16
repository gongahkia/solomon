package config

import "testing"

func TestSetValidatesMode(t *testing.T) {
	cfg := Default()
	if err := cfg.Set("mode", "interrupt"); err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "interrupt" {
		t.Fatal(cfg.Mode)
	}
	if err := cfg.Set("mode", "unsafe"); err == nil {
		t.Fatal("expected error")
	}
}

func TestDefaultIsNonBlocking(t *testing.T) {
	if Default().Mode != "hint" {
		t.Fatal("default must be hint")
	}
}
