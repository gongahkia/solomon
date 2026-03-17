package config

import (
	"os"
	"path/filepath"

	"github.com/BurntSushi/toml"
)

type Config struct {
	Theme        string `toml:"theme"`
	DefaultMode  string `toml:"default_mode"`
	DefaultTime  int    `toml:"default_time"`
	DefaultWords int    `toml:"default_words"`
	WordList     string `toml:"word_list"`
	SmoothCaret  bool   `toml:"smooth_caret"`
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
	fp := filepath.Join(dir(), "config.toml")
	cfg := Default()
	_, err := toml.DecodeFile(fp, cfg)
	if err != nil {
		if os.IsNotExist(err) {
			_ = cfg.Save()
			return cfg, nil
		}
		return cfg, nil // bad file, use defaults
	}
	return cfg, nil
}

func (c *Config) Save() error {
	d := dir()
	if err := os.MkdirAll(d, 0755); err != nil {
		return err
	}
	f, err := os.Create(filepath.Join(d, "config.toml"))
	if err != nil {
		return err
	}
	defer f.Close()
	return toml.NewEncoder(f).Encode(c)
}
