package main

import (
	"embed"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/config"
	"github.com/gongahkia/monke/internal/store"
	"github.com/gongahkia/monke/internal/tui"
	"github.com/gongahkia/monke/internal/wordlist"
)

//go:embed assets/words/*
var assetsFS embed.FS

func main() {
	wordlist.Init(assetsFS)
	cfg, err := config.Load()
	if err != nil {
		cfg = config.Default()
	}
	st, err := store.Open()
	if err != nil {
		fmt.Fprintf(os.Stderr, "warn: store: %v\n", err)
	}
	p := tea.NewProgram(tui.NewApp(cfg, st), tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}
