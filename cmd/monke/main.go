package main

import (
	"embed"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/gongahkia/monke/internal/tui"
	"github.com/gongahkia/monke/internal/wordlist"
)

//go:embed assets/words/*
var assetsFS embed.FS

func main() {
	wordlist.Init(assetsFS)
	p := tea.NewProgram(tui.NewApp(), tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}
