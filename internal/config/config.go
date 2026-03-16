package config

import (
	"encoding/json"
	"os"
	"path/filepath"
)

type Config struct {
	Theme        string `json:"theme"`
	DefaultMode  string `json:"default_mode"`
	DefaultTime  int    `json:"default_time"`
	DefaultWords int    `json:"default_words"`
	WordList     string `json:"word_list"`
	SmoothCaret  bool   `json:"smooth_caret"`
}

func Default() *Config {
	return &Config{
		Theme:        "catppuccin",
		DefaultMode:  "time",
		DefaultTime:  30,
		DefaultWords: 25,
		WordList:     "english_200",
		SmoothCaret:  false,
	}
}

func dir() string {
	d, err := os.UserConfigDir()
	if err != nil {
		d = os.Getenv("HOME")
	}
	return filepath.Join(d, "monke")
}

func Load() (*Config, error) {
	fp := filepath.Join(dir(), "config.json")
	raw, err := os.ReadFile(fp)
	if err != nil {
		if os.IsNotExist(err) {
			cfg := Default()
			_ = cfg.Save() // create default config
			return cfg, nil
		}
		return nil, err
	}
	cfg := Default()
	if err := json.Unmarshal(raw, cfg); err != nil {
		return Default(), nil
	}
	return cfg, nil
}

func (c *Config) Save() error {
	d := dir()
	if err := os.MkdirAll(d, 0755); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(d, "config.json"), raw, 0644)
}
